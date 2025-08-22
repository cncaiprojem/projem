/**
 * File Uploader Component for Task 5.8
 * Turkish UI with drag-and-drop, file validation, and upload progress
 */

'use client';

import React, { useState, useRef, useCallback, DragEvent } from 'react';
import { useUpload } from '@/hooks/useUpload';
import { UploadProgress } from './UploadProgress';

interface FileUploaderProps {
  jobId: string;
  machineId?: string;
  postProcessor?: string;
  onUploadComplete?: (result: any) => void;
  maxSize?: number;
  allowedExtensions?: string[];
  className?: string;
}

export function FileUploader({
  jobId,
  machineId,
  postProcessor,
  onUploadComplete,
  maxSize,
  allowedExtensions,
  className = '',
}: FileUploaderProps) {
  // State
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  
  // Refs
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);

  // Upload hook
  const {
    upload,
    cancel,
    reset,
    progress,
    result,
    isUploading,
  } = useUpload({
    jobId,
    machineId,
    postProcessor,
    maxSize,
    allowedExtensions,
    onSuccess: (uploadResult) => {
      setUploadError(null);
      if (onUploadComplete) {
        onUploadComplete(uploadResult);
      }
      // Clear file after successful upload
      setTimeout(() => {
        setSelectedFile(null);
        reset();
      }, 3000);
    },
    onError: (error, code) => {
      setUploadError(error);
      console.error('Upload error:', error, code);
    },
  });

  /**
   * Handle file selection
   */
  const handleFileSelect = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;

    const file = files[0];
    setSelectedFile(file);
    setUploadError(null);
  }, []);

  /**
   * Handle drag enter
   */
  const handleDragEnter = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    dragCounterRef.current++;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  }, []);

  /**
   * Handle drag leave
   */
  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  /**
   * Handle drag over
   */
  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  /**
   * Handle drop
   */
  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    setIsDragging(false);
    dragCounterRef.current = 0;
    
    const files = e.dataTransfer.files;
    handleFileSelect(files);
  }, [handleFileSelect]);

  /**
   * Format file size
   */
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bayt';
    const k = 1024;
    const sizes = ['Bayt', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  /**
   * Get file icon based on extension
   */
  const getFileIcon = (fileName: string): string => {
    const ext = fileName.toLowerCase().split('.').pop();
    switch (ext) {
      case 'stl':
      case 'step':
      case 'fcstd':
      case 'glb':
        return '📐'; // CAD model
      case 'gcode':
      case 'nc':
      case 'tap':
        return '⚙️'; // G-code
      case 'pdf':
        return '📄'; // Document
      case 'mp4':
      case 'gif':
        return '🎬'; // Media
      case 'png':
      case 'jpg':
      case 'jpeg':
        return '🖼️'; // Image
      default:
        return '📎'; // Generic file
    }
  };

  /**
   * Start upload
   */
  const handleStartUpload = useCallback(async () => {
    if (!selectedFile) return;
    await upload(selectedFile);
  }, [selectedFile, upload]);

  /**
   * Cancel upload
   */
  const handleCancelUpload = useCallback(() => {
    cancel();
    setSelectedFile(null);
    setUploadError(null);
  }, [cancel]);

  /**
   * Clear selection
   */
  const handleClearSelection = useCallback(() => {
    setSelectedFile(null);
    setUploadError(null);
    reset();
  }, [reset]);

  return (
    <div className={`file-uploader ${className}`}>
      {/* Drop zone */}
      {!selectedFile && !isUploading && (
        <div
          className={`
            border-2 border-dashed rounded-lg p-8 text-center transition-all
            ${isDragging 
              ? 'border-blue-500 bg-blue-50 scale-105' 
              : 'border-gray-300 hover:border-gray-400'
            }
          `}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <div className="mb-4">
            <svg
              className="mx-auto h-12 w-12 text-gray-400"
              stroke="currentColor"
              fill="none"
              viewBox="0 0 48 48"
              aria-hidden="true"
            >
              <path
                d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          
          <p className="text-lg font-medium text-gray-900 mb-2">
            {isDragging ? 'Dosyayı buraya bırakın' : 'Dosya Yükle'}
          </p>
          
          <p className="text-sm text-gray-500 mb-4">
            Dosyayı sürükleyip bırakın veya seçmek için tıklayın
          </p>
          
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(e) => handleFileSelect(e.target.files)}
            accept={allowedExtensions?.map(ext => ext).join(',')}
          />
          
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Dosya Seç
          </button>
          
          <div className="mt-4 text-xs text-gray-500">
            <p>Maksimum dosya boyutu: {formatFileSize(maxSize || 200 * 1024 * 1024)}</p>
            {allowedExtensions && (
              <p>İzin verilen türler: {allowedExtensions.join(', ')}</p>
            )}
          </div>
        </div>
      )}

      {/* Selected file display */}
      {selectedFile && !isUploading && progress.status !== 'success' && (
        <div className="border rounded-lg p-4 bg-gray-50">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-3">
              <span className="text-2xl">{getFileIcon(selectedFile.name)}</span>
              <div>
                <p className="font-medium text-gray-900">{selectedFile.name}</p>
                <p className="text-sm text-gray-500">{formatFileSize(selectedFile.size)}</p>
              </div>
            </div>
            <button
              onClick={handleClearSelection}
              className="text-gray-400 hover:text-gray-500"
            >
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
          
          {uploadError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-800">{uploadError}</p>
            </div>
          )}
          
          <button
            onClick={handleStartUpload}
            disabled={isUploading}
            className="w-full inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Yüklemeyi Başlat
          </button>
        </div>
      )}

      {/* Upload progress */}
      {(isUploading || progress.status === 'success') && (
        <UploadProgress
          progress={progress}
          fileName={selectedFile?.name || ''}
          fileSize={selectedFile?.size || 0}
          onCancel={handleCancelUpload}
        />
      )}

      {/* Success message with metadata */}
      {progress.status === 'success' && result && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-start">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-green-400"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-green-800">
                Dosya başarıyla yüklendi!
              </h3>
              <div className="mt-2 text-sm text-green-700">
                <p>Artefakt ID: {result.artefactId}</p>
                <p>SHA256: {result.sha256.substring(0, 16)}...</p>
                <p>Tür: {result.type}</p>
                <p>Boyut: {formatFileSize(result.size)}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}