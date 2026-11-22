import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import App from './App';
import { restoreSession } from './api/client';
import './index.css';

restoreSession();
const queryClient = new QueryClient({ defaultOptions: {
  queries: { staleTime: 10000, retry: false }, mutations: { retry: false },
} });
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={queryClient}>
    <App /><Toaster position="top-right" />
  </QueryClientProvider></React.StrictMode>,
);
