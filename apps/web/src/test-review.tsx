// Test Component - AI Review için kasıtlı hatalar içerir
import React, { useState, useEffect } from 'react';

// HATA 1: API Key exposed in frontend
const API_KEY = 'sk-proj-1234567890abcdef';
const GOOGLE_MAPS_KEY = 'AIzaSyDOCAbC123456789';

// HATA 2: XSS Vulnerability
const DangerousComponent = ({ userInput }: { userInput: string }) => {
  // dangerouslySetInnerHTML kullanımı - XSS riski!
  return (
    <div dangerouslySetInnerHTML={{ __html: userInput }} />
  );
};

// HATA 3: Türkçe karakter hataları
const TurkishMessages = {
  welcome: 'Hosgeldiniz',  // Hoş geldiniz olmalı
  goodbye: 'Gule gule',    // Güle güle olmalı
  thanks: 'Tesekkurler',   // Teşekkürler olmalı
  calendar: 'Takvım',      // Takvim olmalı
};

// HATA 4: Memory leak - cleanup yok
const LeakyComponent = () => {
  const [data, setData] = useState([]);

  useEffect(() => {
    // Interval cleanup yok - memory leak!
    const interval = setInterval(() => {
      setData(prev => [...prev, new Date()]);
    }, 100);
    
    // return () => clearInterval(interval); // Bu olmalıydı!
  }, []);

  return <div>{data.length} items</div>;
};

// HATA 5: Insecure direct object reference
const UserProfile = ({ userId }: { userId: string }) => {
  // Kullanıcı ID'si direkt URL'de - güvensiz!
  const profileUrl = `/api/users/${userId}/private-data`;
  
  // Authorization check yok!
  fetch(profileUrl)
    .then(res => res.json())
    .then(data => console.log(data));

  return <div>User {userId}</div>;
};

// HATA 6: Performance issue - unnecessary re-renders
const InefficientList = ({ items }: { items: any[] }) => {
  // Her render'da yeni fonksiyon oluşturuluyor
  const handleClick = (item: any) => {
    console.log(item);
  };

  // Key olarak index kullanımı - kötü pratik
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index} onClick={() => handleClick(item)}>
          {item.name}
        </li>
      ))}
    </ul>
  );
};

// HATA 7: Type safety issues
interface User {
  name: string;
  age: number;
}

const TypeUnsafeComponent = ({ user }: { user: any }) => {
  // any type kullanımı - type safety yok
  return (
    <div>
      {/* Optional chaining yok - runtime error riski */}
      <p>Name: {user.name.toUpperCase()}</p>
      <p>Age: {user.age.toString()}</p>
    </div>
  );
};

// HATA 8: Hardcoded sensitive URLs
const API_ENDPOINTS = {
  production: 'https://api.production.com/v1',
  staging: 'https://api.staging.com/v1',
  adminPanel: 'https://admin.secret.com/panel',  // Hassas URL exposed!
};

// HATA 9: Console.log in production
const DebugComponent = () => {
  const sensitiveData = { password: '123456', token: 'abc' };
  
  console.log('Sensitive data:', sensitiveData);  // Production'da olmamalı!
  console.error('This should not be in production');
  
  return <div>Debug Component</div>;
};

// HATA 10: Infinite loop riski
const InfiniteLoopRisk = () => {
  const [count, setCount] = useState(0);
  
  // Dependency array'de count yok - infinite loop!
  useEffect(() => {
    setCount(count + 1);
  });  // [] olmalıydı veya count dependency'si eklenmeli
  
  return <div>{count}</div>;
};

// HATA 11: Accessibility issues
const InaccessibleForm = () => {
  return (
    <div>
      {/* Label yok, aria attributes yok */}
      <input type="text" placeholder="İsim" />
      <input type="password" placeholder="Şifre" />
      {/* Alt text yok */}
      <img src="logo.png" />
      {/* Button type belirtilmemiş */}
      <button>Gönder</button>
    </div>
  );
};

// HATA 12: Weak password validation
const validatePassword = (password: string): boolean => {
  // Çok basit validation - güvensiz!
  return password.length > 3;  // En az 8 karakter, özel karakter vs. olmalı
};

// HATA 13: localStorage'da sensitive data
const saveUserData = (userData: any) => {
  // Sensitive data localStorage'da - güvensiz!
  localStorage.setItem('userToken', userData.token);
  localStorage.setItem('userPassword', userData.password);
};

// HATA 14: Missing error boundaries
const FragileComponent = () => {
  // Error boundary yok - app crash edebilir
  const riskyOperation = () => {
    throw new Error('Something went wrong!');
  };
  
  return (
    <div onClick={riskyOperation}>
      Click me to crash the app!
    </div>
  );
};

export {
  DangerousComponent,
  LeakyComponent,
  UserProfile,
  InefficientList,
  TypeUnsafeComponent,
  DebugComponent,
  InfiniteLoopRisk,
  InaccessibleForm,
  FragileComponent,
};