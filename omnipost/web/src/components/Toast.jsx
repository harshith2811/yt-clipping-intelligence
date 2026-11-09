import React from 'react';
import { CheckCircle, AlertCircle } from 'lucide-react';

export default function Toast({ toasts = [] }) {
  return (
    <div className="toast-container" id="toast-container">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.type}`}>
          {toast.type === 'success' ? (
            <CheckCircle size={18} color="#10B981" />
          ) : (
            <AlertCircle size={18} color="#EF4444" />
          )}
          <span>{toast.message}</span>
        </div>
      ))}
    </div>
  );
}
