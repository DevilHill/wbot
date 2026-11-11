import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { AuthenticationBoundary } from './auth-page';
import './styles.css';

createRoot(document.getElementById('root')!).render(<StrictMode><AuthenticationBoundary><App /></AuthenticationBoundary></StrictMode>);
