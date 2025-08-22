/**
 * Upload Progress Component for Task 5.8
 * Shows upload progress with speed, ETA, and status
 */

'use client';

import React from 'react';
import type { UploadProgress as UploadProgressType } from '@/hooks/useUpload';

/**
 * Format bytes to human readable size - Moved outside component for performance
 */
const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 Bayt';
  const k = 1024;
  const sizes = ['Bayt', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

/**
 * Format speed to human readable - Moved outside component for performance
 */
const formatSpeed = (bytesPerSecond: number): string => {
  if (bytesPerSecond === 0) return '0 KB/s';
  const k = 1024;
  if (bytesPerSecond < k) {
    return `${Math.round(bytesPerSecond)} B/s`;
  } else if (bytesPerSecond < k * k) {
    return `${(bytesPerSecond / k).toFixed(1)} KB/s`;
  } else {
    return `${(bytesPerSecond / (k * k)).toFixed(1)} MB/s`;
  }
};

/**
 * Format ETA to human readable time - Moved outside component for performance
 */
const formatETA = (seconds: number): string => {
  if (!seconds || seconds === 0 || !isFinite(seconds)) return '--';
  
  if (seconds < 60) {
    return `${Math.round(seconds)} saniye`;
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${minutes} dakika ${secs > 0 ? `${secs} saniye` : ''}`.trim();
  } else {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours} saat ${minutes > 0 ? `${minutes} dakika` : ''}`.trim();
  }
};

/**
 * Get status message in Turkish - Moved outside component for performance
 */
const getStatusMessage = (status: UploadProgressType['status']): string => {
  switch (status) {
    case 'hashing':
      return 'Dosya hash değeri hesaplanıyor...';
    case 'initializing':
      return 'Yükleme başlatılıyor...';
    case 'uploading':
      return 'Dosya yükleniyor...';
    case 'finalizing':
      return 'Yükleme tamamlanıyor...';
    case 'success':
      return 'Yükleme başarıyla tamamlandı!';
    case 'error':
      return 'Yükleme hatası';
    default:
      return 'Bekliyor...';
  }
};

/**
 * Get progress bar color based on status - Moved outside component for performance
 */
const getProgressBarColor = (status: UploadProgressType['status']): string => {
  switch (status) {
    case 'success':
      return 'bg-green-600';
    case 'error':
      return 'bg-red-600';
    case 'hashing':
      return 'bg-yellow-600';
    default:
      return 'bg-blue-600';
  }
};

/**
 * Get status icon - Moved outside component for performance
 */
const getStatusIcon = (status: UploadProgressType['status']) => {
  switch (status) {
    case 'success':
      return (
        <svg className="h-5 w-5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
            clipRule="evenodd"
          />
        </svg>
      );
    case 'error':
      return (
        <svg className="h-5 w-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
            clipRule="evenodd"
          />
        </svg>
      );
    case 'hashing':
      return (
        <svg className="animate-spin h-5 w-5 text-yellow-500" fill="none" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      );
    default:
      return (
        <svg className="animate-spin h-5 w-5 text-blue-500" fill="none" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      );
  }
};

interface UploadProgressProps {
  progress: UploadProgressType;
  fileName: string;
  fileSize: number;
  onCancel?: () => void;
}

export function UploadProgress({
  progress,
  fileName,
  fileSize,
  onCancel,
}: UploadProgressProps) {

  const isActive = progress.status !== 'idle' && progress.status !== 'success' && progress.status !== 'error';

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-3">
          {getStatusIcon(progress.status)}
          <div className="flex-1">
            <p className="text-sm font-medium text-gray-900">{fileName}</p>
            <p className="text-xs text-gray-500">{getStatusMessage(progress.status)}</p>
          </div>
        </div>
        
        {isActive && onCancel && (
          <button
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-500 p-1 rounded hover:bg-gray-100"
            title="İptal"
          >
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
          <span>{Math.round(progress.progress)}%</span>
          <span>
            {formatBytes(progress.bytesUploaded)} / {formatBytes(progress.totalBytes || fileSize)}
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${getProgressBarColor(progress.status)}`}
            style={{ width: `${Math.min(100, Math.max(0, progress.progress))}%` }}
          />
        </div>
      </div>

      {/* Speed and ETA */}
      {progress.status === 'uploading' && (
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>Hız: {formatSpeed(progress.speed)}</span>
          <span>Tahmini süre: {formatETA(progress.eta)}</span>
        </div>
      )}

      {/* Error message */}
      {progress.error && (
        <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded">
          <p className="text-xs text-red-800">{progress.error}</p>
          {progress.errorCode && (
            <p className="text-xs text-red-600 mt-1">Hata kodu: {progress.errorCode}</p>
          )}
        </div>
      )}

      {/* Success details */}
      {progress.status === 'success' && (
        <div className="mt-3 p-2 bg-green-50 border border-green-200 rounded">
          <p className="text-xs text-green-800">
            Dosya başarıyla yüklendi! Toplam boyut: {formatBytes(fileSize)}
          </p>
        </div>
      )}
    </div>
  );
}