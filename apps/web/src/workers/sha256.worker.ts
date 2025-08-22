/**
 * Web Worker for streaming SHA256 computation
 * Task 5.8 - Computes SHA256 hash of files without blocking main thread
 */

// Import js-sha256 for true streaming hash computation
import { sha256 } from 'js-sha256';

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
 * Process file in chunks and compute SHA256 using true streaming
 */
async function computeSHA256(file: File, chunkSize: number = DEFAULT_CHUNK_SIZE): Promise<{ hash: string; duration: number }> {
  const startTime = performance.now();
  let position = 0;
  const totalSize = file.size;
  
  // Initialize streaming hash computation
  const hash = sha256.create();
  
  while (position < totalSize) {
    // Calculate chunk boundaries
    const end = Math.min(position + chunkSize, totalSize);
    
    // Read chunk using File.slice()
    const chunk = file.slice(position, end);
    const arrayBuffer = await chunk.arrayBuffer();
    
    // Update hash with chunk (true streaming - no memory accumulation)
    hash.update(arrayBuffer);
    
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
  
  // Get final hash in hex format
  const hexHash = hash.hex();
  
  // Calculate duration
  const duration = performance.now() - startTime;
  
  return { hash: hexHash, duration };
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
      
      // Compute hash (now returns both hash and duration)
      const result = await computeSHA256(data.file, data.chunkSize);
      
      // Send result
      self.postMessage({
        type: 'result',
        hash: result.hash,
        duration: result.duration
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