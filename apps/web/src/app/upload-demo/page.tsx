/**
 * Demo page for testing FileUploader component
 * Task 5.8 - Frontend uploader with Web Worker SHA256
 */

'use client';

import React from 'react';
import { FileUploader } from '@/components/FileUploader';
import type { UploadResult } from '@/hooks/useUpload';

export default function UploadDemoPage() {
  const handleUploadComplete = (result: UploadResult) => {
    console.log('Upload complete:', result);
  };

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white shadow rounded-lg p-6">
          <h1 className="text-2xl font-bold text-gray-900 mb-6">
            Dosya Yükleme Demo
          </h1>
          
          <div className="mb-8">
            <h2 className="text-lg font-medium text-gray-700 mb-2">
              Test Bilgileri
            </h2>
            <div className="bg-gray-50 rounded p-4 text-sm text-gray-600">
              <p className="mb-2">
                <strong>İzin verilen dosya türleri:</strong> .step, .stl, .fcstd, .glb, .nc, .gcode, .pdf, .mp4, .gif
              </p>
              <p className="mb-2">
                <strong>Maksimum dosya boyutu:</strong> 200MB
              </p>
              <p className="mb-2">
                <strong>SHA256 hesaplama:</strong> Web Worker ile arka planda
              </p>
              <p>
                <strong>Yükleme akışı:</strong> Hash → Init → Upload → Finalize
              </p>
            </div>
          </div>

          <FileUploader
            jobId="demo-job-001"
            machineId="machine-01"
            postProcessor="post-01"
            onUploadComplete={handleUploadComplete}
          />

          <div className="mt-8 border-t pt-6">
            <h3 className="text-md font-medium text-gray-700 mb-3">
              Test Senaryoları
            </h3>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-2">
              <li>200MB&apos;dan büyük dosya yüklemeyi deneyin (hata mesajı gösterilmeli)</li>
              <li>Desteklenmeyen dosya türü yüklemeyi deneyin (.exe, .bat vb.)</li>
              <li>Çift uzantılı dosya yüklemeyi deneyin (güvenlik uyarısı gösterilmeli)</li>
              <li>Dosyayı sürükleyip bırakarak yüklemeyi test edin</li>
              <li>Yükleme sırasında iptal etmeyi test edin</li>
              <li>Başarılı yükleme sonrası metadata görüntülenmeli</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}