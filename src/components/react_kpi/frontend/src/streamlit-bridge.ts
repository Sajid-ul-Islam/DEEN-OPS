import { useState, useEffect, useCallback } from 'react';
import { ComponentArgs, StreamlitRenderMessage } from './types';

// Default mock data for local testing or when developing in browser
export const DEFAULT_MOCK_ARGS: ComponentArgs = {
  views: ["All Orders", "Today Shipped", "Last Day Shipped", "Queue"],
  selectedView: "All Orders",
  viewCounts: {
    "All Orders": 184,
    "Today Shipped": 32,
    "Last Day Shipped": 45,
    "Queue": 18
  },
  metrics: {
    revenue: {
      label: "Dispatched Revenue",
      value: "148,520",
      prefix: "৳",
      delta: { value: "+18,200", pct: 14.0, positive: true, text: "+14.0% vs prev" },
      sparkline: [40, 55, 60, 48, 75, 90, 85, 95]
    },
    orders: {
      label: "Dispatched Orders",
      value: "32",
      delta: { value: "+4", pct: 14.3, positive: true, text: "+4 vs prev" },
      sparkline: [12, 15, 18, 14, 22, 28, 25, 32]
    },
    units: {
      label: "Dispatched Units",
      value: "68",
      subtext: "Items shipped",
      sparkline: [25, 30, 40, 35, 52, 60, 58, 68]
    },
    aov: {
      label: "Average Order Value",
      value: "4,641",
      prefix: "৳",
      delta: { value: "-120", pct: -2.5, positive: false, text: "-2.5% vs prev" },
      sparkline: [4800, 4700, 4500, 4600, 4750, 4641]
    }
  },
  customerMix: {
    newCount: 21,
    returningCount: 11,
    returningRatio: 34.4
  },
  syncTime: "Just now"
};

export function useStreamlitBridge() {
  const [args, setArgs] = useState<ComponentArgs>(DEFAULT_MOCK_ARGS);
  const [disabled, setDisabled] = useState<boolean>(false);
  const [theme, setTheme] = useState<StreamlitRenderMessage["theme"] | undefined>();

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const data = event.data as StreamlitRenderMessage;
      if (data && data.type === "streamlit:render") {
        if (data.args) {
          const resolvedArgs = (data.args as any)?.args
            ? { ...data.args, ...(data.args as any).args }
            : data.args;
          setArgs(resolvedArgs);
        }
        if (data.theme) {
          setTheme(data.theme);
          let isDark = data.theme.base === "dark";
          if (data.theme.backgroundColor) {
            const hex = data.theme.backgroundColor.replace('#', '');
            if (hex.length === 6) {
              const r = parseInt(hex.substring(0, 2), 16);
              const g = parseInt(hex.substring(2, 4), 16);
              const b = parseInt(hex.substring(4, 6), 16);
              const lum = 0.299 * r + 0.587 * g + 0.114 * b;
              isDark = lum < 128;
            }
          }
          try {
            const pDoc = window.parent.document;
            const pTheme = pDoc.documentElement.getAttribute('data-theme') || (pDoc.body && pDoc.body.getAttribute('data-theme'));
            if (pTheme === 'light') isDark = false;
            else if (pTheme === 'dark') isDark = true;
          } catch (e) {
            // cross-origin fallback
          }
          if (isDark) {
            document.documentElement.classList.add("dark");
            document.documentElement.classList.remove("light");
          } else {
            document.documentElement.classList.remove("dark");
            document.documentElement.classList.add("light");
          }
        }

        setDisabled(!!data.disabled);
      }
    };

    window.addEventListener("message", handleMessage);

    // Notify Streamlit that component is ready to receive data
    window.parent.postMessage(
      { isStreamlitMessage: true, type: "streamlit:componentReady", apiVersion: 1 },
      "*"
    );

    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, []);

  const sendValue = useCallback((value: unknown) => {
    window.parent.postMessage(
      {
        isStreamlitMessage: true,
        type: "streamlit:setComponentValue",
        value: value,
      },
      "*"
    );
  }, []);

  const updateHeight = useCallback((height?: number) => {
    const h = height ?? Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    window.parent.postMessage(
      {
        isStreamlitMessage: true,
        type: "streamlit:setFrameHeight",
        height: h + 16,
      },
      "*"
    );
  }, []);


  return { args, disabled, theme, sendValue, updateHeight };
}
