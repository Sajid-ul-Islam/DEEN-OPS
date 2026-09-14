import React, { useEffect, useRef } from 'react';
import { useStreamlitBridge } from './streamlit-bridge';
import { ViewSwitcher } from './components/ViewSwitcher';
import { KPICard } from './components/KPICard';
import { CustomerMix } from './components/CustomerMix';
import { Clock } from 'lucide-react';

export const App: React.FC = () => {
  const { args, disabled, sendValue, updateHeight } = useStreamlitBridge();
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-resize Streamlit iframe whenever content renders or changes
  useEffect(() => {
    updateHeight();
    const timer = setTimeout(() => updateHeight(), 50);
    return () => clearTimeout(timer);
  }, [args, updateHeight]);

  const handleSelectView = (view: string) => {
    sendValue(view);
  };

  const rawData = (args as any)?.args ? { ...args, ...(args as any).args } : args;
  const { views, selectedView, viewCounts, metrics, customerMix, syncTime } = rawData || {};

  return (
    <div ref={containerRef} className="w-full text-slate-900 dark:text-slate-100 p-1 select-none font-sans">
      {/* Top Bar: View Switcher + Live Sync Badge */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <ViewSwitcher
          views={views || []}
          selectedView={selectedView || "All Orders"}
          viewCounts={viewCounts || {}}
          onSelectView={handleSelectView}
          disabled={disabled}
        />

        {syncTime && (
          <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400 bg-slate-100/90 dark:bg-slate-900/60 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-800">
            <Clock className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 animate-pulse" />
            <span>Synced: <strong className="text-slate-800 dark:text-slate-300">{syncTime}</strong></span>
          </div>
        )}
      </div>

      {/* 5-Column Responsive Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
        {metrics?.revenue && (
          <KPICard metric={metrics.revenue} accent="emerald" />
        )}
        {metrics?.orders && (
          <KPICard metric={metrics.orders} accent="emerald" />
        )}
        {metrics?.units && (
          <KPICard metric={metrics.units} accent="blue" />
        )}
        {metrics?.aov && (
          <KPICard metric={metrics.aov} accent="amber" />
        )}
        {customerMix && (
          <CustomerMix data={customerMix} />
        )}
      </div>
    </div>
  );
};
