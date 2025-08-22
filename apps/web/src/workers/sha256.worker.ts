/**
 * Web Worker for streaming SHA256 computation
 * Task 5.8 - Computes SHA256 hash of files without blocking main thread
 */

interface HashRequest {
  type: 'hash';
  file: File;
  chunkSize?: number;
}

interface HashProgress {
  type: 'progress';
  progress: number;
  bytesProcessed: number;
  totalBytes: number;
}

interface HashResult {
  type: 'result';
  hash: string;
  duration: number;
}

interface HashError {
  type: 'error';
  error: string;
}

type WorkerMessage = HashRequest;
type WorkerResponse = HashProgress | HashResult | HashError;

// Default chunk size: 2MB for optimal performance
const DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024;

/**
 * Convert ArrayBuffer to hex string
 */
function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Process file in chunks and compute SHA256
 */
async function computeSHA256(file: File, chunkSize: number = DEFAULT_CHUNK_SIZE): Promise<string> {
  const startTime = performance.now();
  let position = 0;
  const totalSize = file.size;
  
  // Initialize hash computation
  const hashBuffer: ArrayBuffer[] = [];
  
  while (position < totalSize) {
    // Calculate chunk boundaries
    const end = Math.min(position + chunkSize, totalSize);
    
    // Read chunk using File.slice()
    const chunk = file.slice(position, end);
    const arrayBuffer = await chunk.arrayBuffer();
    
    // Store chunk for hashing
    hashBuffer.push(arrayBuffer);
    
    // Update position
    position = end;
    
    // Report progress
    const progress = (position / totalSize) * 100;
    self.postMessage({
      type: 'progress',
      progress,
      bytesProcessed: position,
      totalBytes: totalSize
    } as HashProgress);
  }
  
  // Combine all chunks for final hash
  const totalLength = hashBuffer.reduce((acc, buf) => acc + buf.byteLength, 0);
  const combined = new Uint8Array(totalLength);
  let offset = 0;
  
  for (const buffer of hashBuffer) {
    combined.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  }
  
  // Compute SHA256 using Web Crypto API
  const hashArrayBuffer = await crypto.subtle.digest('SHA-256', combined);
  const hash = bufferToHex(hashArrayBuffer);
  
  const duration = performance.now() - startTime;
  
  return hash;
}

/**
 * Handle messages from main thread
 */
self.addEventListener('message', async (event: MessageEvent<WorkerMessage>) => {
  const { data } = event;
  
  if (data.type === 'hash') {
    try {
      // Validate input
      if (!data.file || !(data.file instanceof File)) {
        throw new Error('Geçersiz dosya');
      }
      
      // Compute hash
      const hash = await computeSHA256(data.file, data.chunkSize);
      const duration = performance.now();
      
      // Send result
      self.postMessage({
        type: 'result',
        hash,
        duration
      } as HashResult);
      
    } catch (error) {
      // Send error
      self.postMessage({
        type: 'error',
        error: error instanceof Error ? error.message : 'Bilinmeyen hata'
      } as HashError);
    }
  }
});

// TypeScript export to make this a module
export {};