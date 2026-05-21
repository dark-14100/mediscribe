import { Outlet } from 'react-router-dom';
import Sidebar from '../Sidebar/Sidebar';
import './AppLayout.css';

export default function AppLayout() {
  return (
    <div className="app-layout">
      <Sidebar />
      <div className="app-layout__main">
        <Outlet />
      </div>
    </div>
  );
}
