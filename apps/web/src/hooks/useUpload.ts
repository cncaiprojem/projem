/**
 * Upload Hook for Task 5.8
 * Handles file upload with Web Worker SHA256, presigned URLs, and progress tracking
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '@/lib/api';

// Types
interface UploadProgress {
  status: 'idle' | 'hashing' | 'initializing' | 'uploading' | 'finalizing' | 'success' | 'error';
  progress: number;
  speed: number; // bytes per second
  eta: number; // seconds remaining
  bytesUploaded: number;
  totalBytes: number;
  error?: string;
  errorCode?: string;
}

interface UploadResult {
  artefactId: string;
  objectKey: string;
  size: number;
  type: string;
  sha256: string;
  createdAt: string;
  metadata?: Record<string, any>;
}

interface UseUploadOptions {
  maxSize?: number; // Maximum file size in bytes (default: 200MB)
  allowedExtensions?: string[]; // Allowed file extensions
  allowedMimeTypes?: string[]; // Allowed MIME types
  jobId: string; // Required job ID for upload
  machineId?: string; // Optional machine ID
  postProcessor?: string; // Optional post-processor
  onProgress?: (progress: UploadProgress) => void;
  onSuccess?: (result: UploadResult) => void;
  onError?: (error: string, code?: string) => void;
  autoRetry?: boolean; // Auto-retry on transient failures
  retryCount?: number; // Number of retries (default: 3)
  retryDelay?: number; // Delay between retries in ms (default: 1000)
}

// Constants
const MAX_FILE_SIZE = 200 * 1024 * 1024; // 200MB
const PRESIGNED_URL_TTL = 5 * 60 * 1000; // 5 minutes in ms
const TTL_WARNING_THRESHOLD = 30 * 1000; // Warn if less than 30 seconds left

// Default allowed extensions (from backend)
const DEFAULT_ALLOWED_EXTENSIONS = [
  '.step', '.stl', '.fcstd', '.glb', // CAD/CAM models
  '.nc', '.tap', '.gcode', // G-code
  '.mp4', '.gif', // Media
  '.pdf', '.json', '.csv', '.xml', // Documents
  '.png', '.jpg', '.jpeg', // Images
];

// Map extensions to MIME types
const EXTENSION_TO_MIME: Record<string, string> = {
  '.step': 'model/step',
  '.stl': 'model/stl',
  '.fcstd': 'application/x-freecad',
  '.glb': 'model/gltf-binary',
  '.nc': 'text/plain',
  '.tap': 'text/plain',
  '.gcode': 'text/x-gcode',
  '.mp4': 'video/mp4',
  '.gif': 'image/gif',
  '.pdf': 'application/pdf',
  '.json': 'application/json',
  '.csv': 'text/csv',
  '.xml': 'application/xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
};

// Error messages in Turkish
const ERROR_MESSAGES: Record<string, string> = {
  FILE_TOO_LARGE: 'Dosya boyutu çok büyük (maksimum 200MB)',
  INVALID_TYPE: 'Geçersiz dosya türü',
  DOUBLE_EXTENSION: 'Güvenlik uyarısı: Çift uzantılı dosya tespit edildi',
  HASH_FAILED: 'Dosya hash hesaplaması başarısız',
  INIT_FAILED: 'Yükleme başlatma hatası',
  UPLOAD_FAILED: 'Dosya yükleme hatası',
  FINALIZE_FAILED: 'Yükleme tamamlama hatası',
  EXPIRED_URL: 'Yükleme URL\'si zaman aşımına uğradı',
  NETWORK_ERROR: 'Ağ bağlantı hatası',
  HASH_MISMATCH: 'Dosya bütünlüğü doğrulanamadı',
  RATE_LIMITED: 'Çok fazla yükleme isteği. Lütfen bekleyin.',
  UNSUPPORTED_MIME: 'Desteklenmeyen dosya içerik türü',
};

export function useUpload(options: UseUploadOptions) {
  const {
    maxSize = MAX_FILE_SIZE,
    allowedExtensions = DEFAULT_ALLOWED_EXTENSIONS,
    allowedMimeTypes,
    jobId,
    machineId,
    postProcessor,
    onProgress,
    onSuccess,
    onError,
    autoRetry = true,
    retryCount = 3,
    retryDelay = 1000,
  } = options;

  // State
  const [progress, setProgress] = useState<UploadProgress>({
    status: 'idle',
    progress: 0,
    speed: 0,
    eta: 0,
    bytesUploaded: 0,
    totalBytes: 0,
  });
  const [result, setResult] = useState<UploadResult | null>(null);

  // Refs
  const workerRef = useRef<Worker | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const uploadStartTimeRef = useRef<number>(0);
  const presignedUrlExpiryRef = useRef<number>(0);
  const retryCountRef = useRef<number>(0);

  // Initialize Web Worker
  useEffect(() => {
    // Create a blob URL for the worker script
    const workerScript = `
      const DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024;

      function bufferToHex(buffer) {
        return Array.from(new Uint8Array(buffer))
          .map(b => b.toString(16).padStart(2, '0'))
          .join('');
      }

      async function computeSHA256(file, chunkSize = DEFAULT_CHUNK_SIZE) {
        const startTime = performance.now();
        let position = 0;
        const totalSize = file.size;
        const hashBuffer = [];
        
        while (position < totalSize) {
          const end = Math.min(position + chunkSize, totalSize);
          const chunk = file.slice(position, end);
          const arrayBuffer = await chunk.arrayBuffer();
          hashBuffer.push(arrayBuffer);
          position = end;
          
          const progress = (position / totalSize) * 100;
          self.postMessage({
            type: 'progress',
            progress,
            bytesProcessed: position,
            totalBytes: totalSize
          });
        }
        
        const totalLength = hashBuffer.reduce((acc, buf) => acc + buf.byteLength, 0);
        const combined = new Uint8Array(totalLength);
        let offset = 0;
        
        for (const buffer of hashBuffer) {
          combined.set(new Uint8Array(buffer), offset);
          offset += buffer.byteLength;
        }
        
        const hashArrayBuffer = await crypto.subtle.digest('SHA-256', combined);
        const hash = bufferToHex(hashArrayBuffer);
        const duration = performance.now() - startTime;
        
        return hash;
      }

      self.addEventListener('message', async (event) => {
        const { data } = event;
        
        if (data.type === 'hash') {
          try {
            if (!data.file || !(data.file instanceof File)) {
              throw new Error('Geçersiz dosya');
            }
            
            const hash = await computeSHA256(data.file, data.chunkSize);
            const duration = performance.now();
            
            self.postMessage({
              type: 'result',
              hash,
              duration
            });
            
          } catch (error) {
            self.postMessage({
              type: 'error',
              error: error instanceof Error ? error.message : 'Bilinmeyen hata'
            });
          }
        }
      });
    `;
    
    const blob = new Blob([workerScript], { type: 'application/javascript' });
    const workerUrl = URL.createObjectURL(blob);
    workerRef.current = new Worker(workerUrl);

    return () => {
      workerRef.current?.terminate();
      URL.revokeObjectURL(workerUrl);
    };
  }, []);

  // Update progress callback
  useEffect(() => {
    if (onProgress) {
      onProgress(progress);
    }
  }, [progress, onProgress]);

  /**
   * Validate file before upload
   */
  const validateFile = useCallback((file: File): { valid: boolean; error?: string } => {
    // Check file size
    if (file.size > maxSize) {
      return { valid: false, error: ERROR_MESSAGES.FILE_TOO_LARGE };
    }

    // Check file extension
    const fileName = file.name.toLowerCase();
    const extension = fileName.substring(fileName.lastIndexOf('.'));
    
    if (!allowedExtensions.includes(extension)) {
      return { valid: false, error: ERROR_MESSAGES.INVALID_TYPE };
    }

    // Check for double extensions (security)
    const parts = fileName.split('.');
    if (parts.length > 2) {
      // Check if any middle parts look like executable extensions
      const dangerousExtensions = ['exe', 'bat', 'cmd', 'sh', 'ps1', 'vbs', 'js'];
      for (let i = 1; i < parts.length - 1; i++) {
        if (dangerousExtensions.includes(parts[i])) {
          return { valid: false, error: ERROR_MESSAGES.DOUBLE_EXTENSION };
        }
      }
    }

    // Check MIME type if specified
    if (allowedMimeTypes && !allowedMimeTypes.includes(file.type)) {
      return { valid: false, error: ERROR_MESSAGES.UNSUPPORTED_MIME };
    }

    return { valid: true };
  }, [maxSize, allowedExtensions, allowedMimeTypes]);

  /**
   * Compute SHA256 hash using Web Worker
   */
  const computeHash = useCallback((file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      if (!workerRef.current) {
        reject(new Error('Worker not initialized'));
        return;
      }

      const handleMessage = (event: MessageEvent) => {
        const { data } = event;
        
        if (data.type === 'progress') {
          setProgress(prev => ({
            ...prev,
            status: 'hashing',
            progress: data.progress * 0.2, // Hash is 20% of total progress
          }));
        } else if (data.type === 'result') {
          workerRef.current?.removeEventListener('message', handleMessage);
          resolve(data.hash);
        } else if (data.type === 'error') {
          workerRef.current?.removeEventListener('message', handleMessage);
          reject(new Error(data.error));
        }
      };

      workerRef.current.addEventListener('message', handleMessage);
      workerRef.current.postMessage({ type: 'hash', file });
    });
  }, []);

  /**
   * Initialize upload with backend
   */
  const initializeUpload = useCallback(async (
    file: File,
    hash: string
  ): Promise<{ uploadId: string; presignedUrl: string; key: string }> => {
    const fileName = file.name.toLowerCase();
    const extension = fileName.substring(fileName.lastIndexOf('.'));
    const mimeType = EXTENSION_TO_MIME[extension] || file.type || 'application/octet-stream';

    const response = await api.post<{
      upload_id: string;
      presigned_url: string;
      key: string;
      ttl_seconds: number;
    }>('/files/upload/init', {
      type: 'model', // Default to model type
      size: file.size,
      sha256: hash,
      mime_type: mimeType,
      job_id: jobId,
      machine_id: machineId,
      post_processor: postProcessor,
      filename: file.name,
    });

    // Store URL expiry time
    presignedUrlExpiryRef.current = Date.now() + (response.ttl_seconds || 300) * 1000;

    return {
      uploadId: response.upload_id,
      presignedUrl: response.presigned_url,
      key: response.key,
    };
  }, [jobId, machineId, postProcessor]);

  /**
   * Upload file to presigned URL with progress tracking
   */
  const uploadToPresignedUrl = useCallback(async (
    file: File,
    presignedUrl: string
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      abortControllerRef.current = new AbortController();
      
      // Track upload progress
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) {
          const now = Date.now();
          const elapsed = (now - uploadStartTimeRef.current) / 1000; // seconds
          const bytesUploaded = event.loaded;
          const totalBytes = event.total;
          const speed = elapsed > 0 ? bytesUploaded / elapsed : 0;
          const remaining = totalBytes - bytesUploaded;
          const eta = speed > 0 ? remaining / speed : 0;
          const progressPercent = (bytesUploaded / totalBytes) * 100;

          setProgress({
            status: 'uploading',
            progress: 20 + (progressPercent * 0.7), // 20-90% for upload
            speed,
            eta,
            bytesUploaded,
            totalBytes,
          });
        }
      });

      // Handle completion
      xhr.addEventListener('load', () => {
        if (xhr.status === 200 || xhr.status === 204) {
          resolve();
        } else if (xhr.status === 403) {
          // URL expired
          reject(new Error(ERROR_MESSAGES.EXPIRED_URL));
        } else {
          reject(new Error(`Upload failed: ${xhr.status}`));
        }
      });

      // Handle errors
      xhr.addEventListener('error', () => {
        reject(new Error(ERROR_MESSAGES.NETWORK_ERROR));
      });

      // Check if URL is about to expire
      const timeUntilExpiry = presignedUrlExpiryRef.current - Date.now();
      if (timeUntilExpiry < TTL_WARNING_THRESHOLD) {
        console.warn('Presigned URL nearing expiry:', timeUntilExpiry / 1000, 'seconds left');
      }

      // Send request
      xhr.open('PUT', presignedUrl);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.setRequestHeader('Content-Length', file.size.toString());
      
      uploadStartTimeRef.current = Date.now();
      xhr.send(file);
    });
  }, []);

  /**
   * Finalize upload with backend
   */
  const finalizeUpload = useCallback(async (
    uploadId: string,
    hash: string
  ): Promise<UploadResult> => {
    const response = await api.post<{
      artefact_id: string;
      object_key: string;
      size: number;
      type: string;
      sha256: string;
      created_at: string;
      metadata?: Record<string, any>;
    }>('/files/upload/finalize', {
      upload_id: uploadId,
      sha256: hash,
    });

    return {
      artefactId: response.artefact_id,
      objectKey: response.object_key,
      size: response.size,
      type: response.type,
      sha256: response.sha256,
      createdAt: response.created_at,
      metadata: response.metadata,
    };
  }, []);

  /**
   * Handle upload with retry logic
   */
  const handleUploadWithRetry = useCallback(async (
    file: File,
    hash: string,
    initData?: { uploadId: string; presignedUrl: string; key: string }
  ): Promise<void> => {
    let currentInitData = initData;

    try {
      // Initialize if not already done
      if (!currentInitData) {
        setProgress(prev => ({ ...prev, status: 'initializing', progress: 20 }));
        currentInitData = await initializeUpload(file, hash);
      }

      // Upload to presigned URL
      setProgress(prev => ({ ...prev, status: 'uploading' }));
      await uploadToPresignedUrl(file, currentInitData.presignedUrl);

      // Finalize upload
      setProgress(prev => ({ ...prev, status: 'finalizing', progress: 90 }));
      const uploadResult = await finalizeUpload(currentInitData.uploadId, hash);

      // Success
      setResult(uploadResult);
      setProgress({
        status: 'success',
        progress: 100,
        speed: 0,
        eta: 0,
        bytesUploaded: file.size,
        totalBytes: file.size,
      });

      if (onSuccess) {
        onSuccess(uploadResult);
      }

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      
      // Check if we should retry
      if (autoRetry && retryCountRef.current < retryCount) {
        // Check error type
        const isTransientError = 
          errorMessage.includes('Network') ||
          errorMessage.includes('503') ||
          errorMessage.includes('502') ||
          errorMessage.includes('500');
        
        const isExpiredUrl = errorMessage === ERROR_MESSAGES.EXPIRED_URL;

        if (isTransientError || isExpiredUrl) {
          retryCountRef.current++;
          console.log(`Retrying upload (attempt ${retryCountRef.current}/${retryCount})`);
          
          // Wait before retry
          await new Promise(resolve => setTimeout(resolve, retryDelay * retryCountRef.current));
          
          // If URL expired, reinitialize
          if (isExpiredUrl) {
            currentInitData = undefined;
          }
          
          // Retry
          return handleUploadWithRetry(file, hash, currentInitData);
        }
      }

      // No retry or max retries reached
      throw error;
    }
  }, [
    initializeUpload,
    uploadToPresignedUrl,
    finalizeUpload,
    autoRetry,
    retryCount,
    retryDelay,
    onSuccess,
  ]);

  /**
   * Main upload function
   */
  const upload = useCallback(async (file: File): Promise<void> => {
    try {
      // Reset state
      setProgress({
        status: 'idle',
        progress: 0,
        speed: 0,
        eta: 0,
        bytesUploaded: 0,
        totalBytes: file.size,
      });
      setResult(null);
      retryCountRef.current = 0;

      // Validate file
      const validation = validateFile(file);
      if (!validation.valid) {
        throw new Error(validation.error);
      }

      // Compute hash
      setProgress(prev => ({ ...prev, status: 'hashing' }));
      const hash = await computeHash(file);

      // Upload with retry logic
      await handleUploadWithRetry(file, hash);

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Bilinmeyen hata';
      let errorCode: string | undefined;

      // Map error messages to codes
      if (errorMessage.includes('413')) {
        errorCode = 'PAYLOAD_TOO_LARGE';
      } else if (errorMessage.includes('415')) {
        errorCode = 'UNSUPPORTED_MEDIA_TYPE';
      } else if (errorMessage.includes('422')) {
        errorCode = 'HASH_MISMATCH';
      } else if (errorMessage.includes('429')) {
        errorCode = 'RATE_LIMITED';
      }

      setProgress(prev => ({
        ...prev,
        status: 'error',
        error: errorMessage,
        errorCode,
      }));

      if (onError) {
        onError(errorMessage, errorCode);
      }
    }
  }, [
    validateFile,
    computeHash,
    handleUploadWithRetry,
    onError,
  ]);

  /**
   * Cancel ongoing upload
   */
  const cancel = useCallback(() => {
    abortControllerRef.current?.abort();
    workerRef.current?.terminate();
    
    // Note: Worker will be recreated on next upload since it's initialized in useEffect

    setProgress({
      status: 'idle',
      progress: 0,
      speed: 0,
      eta: 0,
      bytesUploaded: 0,
      totalBytes: 0,
    });
  }, []);

  /**
   * Reset upload state
   */
  const reset = useCallback(() => {
    setProgress({
      status: 'idle',
      progress: 0,
      speed: 0,
      eta: 0,
      bytesUploaded: 0,
      totalBytes: 0,
    });
    setResult(null);
    retryCountRef.current = 0;
  }, []);

  return {
    upload,
    cancel,
    reset,
    progress,
    result,
    isUploading: progress.status !== 'idle' && progress.status !== 'success' && progress.status !== 'error',
  };
}