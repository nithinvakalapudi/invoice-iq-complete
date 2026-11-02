import React, { useEffect, useRef, useState } from 'react'
import { Button, Card, Container, Paragraph, Section, VStack } from '@flowstack-ui/brick'
import { api, connectedToken, localOrigin, saveConnection } from './local-api.js'

export default function HostedConnection({ children }) {
  const [ready, setReady] = useState(false)
  const [message, setMessage] = useState('Checking this computer…')
  const popup = useRef(null)

  useEffect(() => {
    if (!connectedToken()) {
      setMessage('Start InvoiceIQ on this computer, then connect it here.')
      return
    }
    api('/config').then(() => setReady(true)).catch(() => {
      setMessage('The local app is unavailable. Start it, then reconnect this tab.')
    })
  }, [])

  useEffect(() => {
    const receive = async (event) => {
      if (event.origin !== localOrigin || event.source !== popup.current ||
          event.data?.type !== 'invoice-local-connection' ||
          typeof event.data.token !== 'string' || event.data.token.length < 40) return
      saveConnection(event.data.token)
      setMessage('Checking the local connection…')
      try {
        await api('/config')
        setReady(true)
      } catch (error) {
        setMessage(`Could not connect: ${error.message}`)
      }
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [])

  if (ready) return children

  const connect = () => {
    // This local page posts the key only to the approved hosted origin.
    const opened = window.open('', 'invoice-iq-connection', 'popup,width=520,height=360')
    if (!opened) {
      setMessage('Allow this site to open the local connection window, then try again.')
      return
    }
    popup.current = opened
    opened.location.replace(`${localOrigin}/bridge/pair`)
  }

  return <Section spacing="xl"><Container measure="sm"><Card.Root variant="outline" size="lg">
    <Card.Header><Card.Title as="h1">Connect InvoiceIQ on this computer</Card.Title>
      <Card.Description>The hosted interface uses the invoice app and classic Outlook running on this computer.</Card.Description>
    </Card.Header>
    <Card.Content><VStack gap={4}>
      <Paragraph role="status" aria-live="polite">{message}</Paragraph>
      <Paragraph>Start the local app at <a href={localOrigin} target="_blank" rel="noopener noreferrer">127.0.0.1:8505</a>, then select Connect. Your browser may ask to allow access to this computer.</Paragraph>
    </VStack></Card.Content>
    <Card.Footer><Button onPress={connect} tone="accent">Connect this computer</Button></Card.Footer>
  </Card.Root></Container></Section>
}
