import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

const server = await createServer({
  root: '/workspace',
  server: { middlewareMode: true },
  appType: 'custom',
});

try {
  const { default: App } = await server.ssrLoadModule('/App.jsx');
  const html = renderToString(React.createElement(App));
  if (!html.includes('Task Manager')) {
    throw new Error('React app did not render its heading');
  }
  console.log('React render smoke passed');
} finally {
  await server.close();
}
