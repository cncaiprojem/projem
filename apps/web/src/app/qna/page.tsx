"use client";
import { useEffect, useState, Suspense } from "react";
import { api } from "@/lib/api";
import { useSearchParams } from "next/navigation";

function QnaContent() {
  const sp = useSearchParams();
  const pid = sp.get("projectId");
  const [missing,setMissing] = useState<string[]>([]);
  const [answers,setAnswers] = useState<Record<string,string>>({});

  useEffect(()=>{
    // Basit: mevcut plandan missing çekmek için ileride /projects/{id} kullanılacak
  },[pid]);

  async function submit() {
    await api.post("/api/v1/design/answer", {
      project_id: Number(pid),
      answers
    });
    alert("Yanıtlar kaydedildi. CAD üretimine geçeceğiz.");
  }

  return (
    <div className="p-6 space-y-3">
      <h1 className="text-2xl font-semibold">Eksik Bilgiler</h1>
      {missing.length===0 ? (
        <p>Eksik bilgi görünmüyor. Devam edebilirsiniz.</p>
      ) : missing.map((m)=>(
        <div key={m} className="flex gap-2">
          <label className="w-48">{m}</label>
          <input className="border p-2 flex-1" onChange={e=>setAnswers(a=>({...a,[m]:e.target.value}))}/>
        </div>
      ))}
      <button onClick={submit} className="px-4 py-2 rounded bg-black text-white">Devam</button>
      <button
        onClick={async ()=>{
          await api.post('/api/v1/cad/build', { project_id: Number(pid), fast_mode: false })
          await api.post('/api/v1/cam2/build', {
            project_id: Number(pid),
            wcs: 'G54',
            stock: { shape: 'block', x_mm: 100, y_mm: 70, z_mm: 10 },
            strategy: 'balanced',
            fast_mode: true,
          })
          alert('CAD ve CAM işleri kuyruğa alındı. /jobs veya viewer’da artefaktları izleyebilirsiniz.')
        }}
        className="px-4 py-2 rounded bg-indigo-600 text-white"
      >
        CAM Başlat
      </button>
    </div>
  );
}

export default function QnaPage() {
  return (
    <Suspense fallback={<div className="p-6"><p>Loading...</p></div>}>
      <QnaContent />
    </Suspense>
  );
}


