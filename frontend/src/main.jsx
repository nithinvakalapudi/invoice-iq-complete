import React from 'react'
import { createRoot } from 'react-dom/client'
import '@flowstack-ui/brick/styles.css'
import './page.css'
import App from './App.jsx'
import HostedConnection from './HostedConnection.jsx'
import { hostedMode } from './local-api.js'

createRoot(document.getElementById('root')).render(hostedMode ? <HostedConnection><App /></HostedConnection> : <App />)
