import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertDialog, AppBar, Badge, Button, Card, Collapsible, Container,
  Dialog, Eyebrow, Field, FileUpload, Grid, Heading, HStack, Input,
  Icon, NavList, NumberInput, Paragraph, Progress, ScrollArea, Section, Sidebar, Table,
  Tabs, Text, VStack,
} from '@flowstack-ui/brick'
import { display, displayAmount, duplicateLabel, filterResults, overviewColumns, statusLabel, statusTone } from './invoice-view.js'
import LocationSettings from './LocationSettings.jsx'
import { api, disconnect, downloadReport, hostedMode } from './local-api.js'
import { withMinimumDisplayDelay } from './minimum-display-delay.js'

const editableFields = [
  ['invoice_number', 'Invoice number'], ['invoice_date', 'Invoice date'],
  ['vendor_name', 'Vendor'], ['region', 'Region (vendor location)'],
  ['currency', 'Currency'], ['subtotal', 'Subtotal'],
  ['customer_name', 'Billed company'],
  ['tax_amount', 'Tax'],
  ['total_amount', 'Total amount'], ['service_start_date', 'Service start date'],
  ['service_end_date', 'Service end date'], ['customer_email', 'Task email'],
  ['vendor_email', 'Email printed on invoice'],
  ['invoice_comments', 'Comments'],
]

const iconPaths = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" /></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m3 7 9 6 9-6" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8m-8 4h5" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>,
  layers: <><path d="m12 3 10 5-10 5L2 8Zm-9 9 9 5 9-5M3 17l9 5 9-5" /></>,
  history: <><path d="M3 11a9 9 0 1 1 2 7M3 4v7h7m2-4v5l3 2" /></>,
  settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" /><circle cx="15" cy="17" r="3" /></>,
  arrow: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
  download: <><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
  refresh: <><path d="M20 7V3l-3 3a8 8 0 0 0-13 4m0 7v4l3-3a8 8 0 0 0 13-4M20 3h-5M4 21h5" /></>,
  shield: <><path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z" /><path d="m8 11 3 3 5-5" /></>,
  alert: <><path d="m10.3 3.5-8 14A2 2 0 0 0 4 20h16a2 2 0 0 0 1.7-2.5l-8-14a2 2 0 0 0-3.4 0Z" /><path d="M12 8v5m0 3h.01" /></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
}

function Artwork({ name }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name] || iconPaths.file}</svg>
}

function Brand({ compact = false }) {
  return <HStack gap={3} align="center">
    <span className="brand-mark"><Artwork name="layers" /></span>
    <VStack gap={0}><Text as="span" variant="title-sm" weight="semibold">Invoice<span className="brand-accent">IQ</span></Text>
      {!compact && <Text as="span" variant="body-xs" tone="muted">Intelligent workflow orchestration</Text>}
    </VStack>
  </HStack>
}

const destinations = [
  ['overview', 'Overview', 'grid'], ['upload', 'Upload invoices', 'upload'],
  ['outlook', 'Outlook inbox', 'mail'], ['results', 'Invoice results', 'file'],
  ['history', 'Saved reports', 'history'], ['settings', 'Settings', 'settings'],
]

function WorkspaceNavigation({ active }) {
  return <NavList.Root variant="soft" tone="accent" size="md" aria-label="Workspace navigation">
    <NavList.Section><NavList.SectionLabel>WORKSPACE</NavList.SectionLabel>
    <NavList.List>{destinations.map(([id, label, icon]) => <NavList.Item key={id}>
      <NavList.Link href={`#${id}`} active={active === id} current={active === id ? 'location' : undefined} startIcon={<Artwork name={icon} />}>{label}</NavList.Link>
    </NavList.Item>)}</NavList.List></NavList.Section>
  </NavList.Root>
}

function DownloadButton({ path, children }) {
  const [error, setError] = useState('')
  if (!hostedMode) return <Button href={`/api/download${path}`} variant="outline" size="sm" startIcon={<Artwork name="download" />}>{children}</Button>
  return <VStack gap={1}><Button onPress={() => downloadReport(path).catch((cause) => setError(cause.message))}
    variant="outline" size="sm" startIcon={<Artwork name="download" />}>{children}</Button>
    {error && <Text as="span" variant="body-xs" tone="danger" role="alert">{error}</Text>}</VStack>
}

function Metric({ label, value, tone = 'neutral' }) {
  return <Card.Root size="sm" variant="outline" className="metric-card">
    <Card.Content><VStack gap={2}>
      <HStack justify="between" align="center"><Text as="span" variant="body-sm" tone="secondary">{label}</Text><span className={`metric-dot metric-dot--${tone}`} /></HStack>
      <Text as="p" variant="title-lg" weight="semibold" tone={tone === 'neutral' ? 'primary' : tone}>{display(value)}</Text>
    </VStack></Card.Content>
  </Card.Root>
}

function ReviewDialog({ batch, index, tolerance, threshold, onSaved, onError }) {
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const result = batch?.results?.[index]
  if (!result || result.processing_status === 'FAILED') return null
  const launch = () => {
    setValues(Object.fromEntries(editableFields.map(([key]) => [key, result.invoice[key] ?? ''])))
    setOpen(true)
  }
  const save = async () => {
    setBusy(true)
    try {
      const updated = await api(`/batches/${batch.batch_id}/review`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ generation: batch.generation, index, fields: values, tolerance, threshold }),
      })
      onSaved(updated)
      setOpen(false)
    } catch (error) { onError(error.message) }
    finally { setBusy(false) }
  }
  return <Dialog.Root open={open} onOpenChange={setOpen}>
    <Button size="sm" variant="ghost" style={{ minInlineSize: '118px', whiteSpace: 'nowrap' }} onPress={launch}>Review details</Button>
    <Dialog.Portal>
      <Dialog.Overlay />
      <Dialog.Content size="lg">
        <Dialog.Header>
          <Dialog.Title>Review invoice</Dialog.Title>
          <Dialog.Description>{result.source_file} · Correct the extracted fields, then revalidate and save.</Dialog.Description>
        </Dialog.Header>
        <Dialog.Body>
          <VStack gap={4}>
            {(result.errors.length || result.warnings.length) > 0 &&
              <Paragraph tone="warning">{[...result.errors, ...result.warnings].join(' · ')}</Paragraph>}
            <Grid.Root columns={{ initial: 1, md: 2 }} gap={3}>
              {editableFields.map(([key, label]) => <Field.Root key={key}>
                <Field.Label>{label}</Field.Label>
                <Input name={key} value={values[key] ?? ''} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
              </Field.Root>)}
            </Grid.Root>
          </VStack>
        </Dialog.Body>
        <Dialog.Footer>
          <Dialog.Close asChild><Button variant="ghost">Cancel</Button></Dialog.Close>
          <Button tone="accent" loading={busy} onPress={save}>Confirm against source and save</Button>
        </Dialog.Footer>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

function Results({ batch, columns, requiredFields, tolerance, threshold, onSaved, onRefresh, onRunMdm, mdmBusy, onError }) {
  const [query, setQuery] = useState('')
  const [view, setView] = useState('overview')
  const [filter, setFilter] = useState('all')
  const [mdmCheck, setMdmCheck] = useState(null)
  const [checkBusy, setCheckBusy] = useState(false)
  const results = batch?.results || []
  const mdmReady = results.length > 0 && results.every((result) => result.mdm_checked === true)
  useEffect(() => { setMdmCheck(null) }, [batch?.batch_id, batch?.mdm_summary])
  const checkMdm = async () => {
    if (!batch?.batch_id || !mdmReady) return
    setCheckBusy(true)
    try {
      setMdmCheck(await withMinimumDisplayDelay(() => api('/mdm/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batch.batch_id, generation: batch.generation }),
      })))
    } catch (err) { onError(err.message) }
    finally { setCheckBusy(false) }
  }
  const shown = useMemo(() => filterResults(results, query, filter), [results, query, filter])
  const table = (names, full = false) => <Table.Container>
    <Table.Root variant="line" size="sm" density="comfortable" stickyHeader style={{ '--brick-table-min-inline-size': full ? '6400px' : '1690px' }}>
      <Table.Caption className="sr-only">{full ? 'All extracted invoice fields' : 'Invoice overview'}</Table.Caption>
      <Table.Header><Table.Row>{names.map((name) => <Table.Head key={name} scope="col">{!full ? ({ 'Vendor -As per MDM': 'Vendor', 'Billing Start Date': 'Service start date', 'Billing End Date': 'Service end date' }[name] || name) : name}</Table.Head>)}<Table.Head scope="col">Details</Table.Head></Table.Row></Table.Header>
      <Table.Body>{shown.map(({ result, index }) => <Table.Row key={`${result.source_file}-${index}`}>
        {names.map((name) => {
          const value = result.mdm_row?.[name]
          if (name === 'Review status') {
            const awaitingMdm = result.mdm_checked !== true && value === 'SUCCESS'
            return <Table.Cell key={name}><Badge tone={awaitingMdm ? 'warning' : statusTone(value)}>{awaitingMdm ? 'Run MDM' : statusLabel(value)}</Badge></Table.Cell>
          }
          if (name === 'Duplicate status' && !full) return <Table.Cell key={name}><Badge tone={value === 'POSSIBLE_DUPLICATE' ? 'warning' : 'neutral'}>{duplicateLabel(value)}</Badge></Table.Cell>
          if (name === 'Invoice Number') return <Table.Head key={name} scope="row"><Text as="span" variant="body-sm" weight="semibold">{display(value)}</Text></Table.Head>
          return <Table.Cell key={name}><span className={['Net Amount', 'Tax Amount', 'Billing Account'].includes(name) ? 'numeric-value' : undefined}>{['Net Amount', 'Tax Amount'].includes(name) ? displayAmount(value) : display(value)}</span></Table.Cell>
        })}
        <Table.Cell><ReviewDialog batch={batch} index={index} tolerance={tolerance} threshold={threshold} onSaved={onSaved} onError={onError} /></Table.Cell>
      </Table.Row>)}</Table.Body>
    </Table.Root>
  </Table.Container>
  if (!batch) return <Section id="results" spacing="md" aria-labelledby="results-heading"><Container measure="max">
    <Card.Root variant="outline" size="lg"><Card.Content><VStack align="center" gap={3} className="empty-state">
      <span className="feature-icon"><Icon size="xl"><Artwork name="file" /></Icon></span>
      <Heading id="results-heading" level={2} variant="title-md">Your next invoice starts here</Heading>
      <Paragraph tone="secondary">Process a file or open a saved batch to see extracted fields, matching results, and downloadable reports.</Paragraph>
      <HStack wrap gap={2}><Button href="#upload" tone="accent" startIcon={<Artwork name="upload" />}>Upload invoices</Button><Button href="#history" variant="outline">View saved reports</Button></HStack>
    </VStack></Card.Content></Card.Root>
  </Container></Section>
  const counts = batch.counts
  return <Section id="results" spacing="md" aria-labelledby="results-heading">
    <Container measure="max"><VStack gap={5}>
      <HStack align="center" justify="between" wrap gap={3}>
        <VStack gap={1}><Eyebrow>YOUR RESULTS</Eyebrow><Heading id="results-heading" level={2} variant="title-lg">From documents to decisions</Heading></VStack>
        <HStack wrap gap={2}><Badge tone="success">Saved locally</Badge><Button size="sm" variant="outline" disabled={mdmBusy} startIcon={<Artwork name="refresh" />} onPress={onRefresh}>Refresh</Button></HStack>
      </HStack>
      <Grid.Root columns={{ initial: 2, md: 3, xl: 9 }} gap={3}>
        <Metric label="Documents" value={counts.total} />
        <Metric label="Processed" value={counts.processed} tone="success" />
        <Metric label="OCR only" value={counts.ocr_only || 0} tone="warning" />
        <Metric label="Auto-approved" value={counts.auto_approved || 0} tone="success" />
        <Metric label="Imported rows" value={counts.imported || 0} />
        <Metric label="Review needed" value={counts.review} tone="warning" />
        <Metric label="Rejected" value={counts.rejected || 0} tone="danger" />
        <Metric label="Failed" value={counts.failed} tone="danger" />
        <Metric label="Duplicates" value={counts.duplicate} tone="warning" />
      </Grid.Root>
      <Card.Root variant="outline" className="results-card">
        <Card.Header><HStack justify="between" wrap align="center" gap={3}>
          <VStack gap={1}><Card.Title as="h3">Invoice results</Card.Title><Card.Description>{shown.length} of {results.length} records · Every attachment, individually processed.</Card.Description></VStack>
          <HStack gap={2}><Button tone="accent" loading={mdmBusy} disabled={mdmBusy} startIcon={<Artwork name="layers" />} onPress={onRunMdm}>{mdmBusy ? 'Running MDM…' : 'Run MDM'}</Button>
            <Button variant="outline" loading={checkBusy} disabled={!mdmReady || mdmBusy || checkBusy} startIcon={<Artwork name="check" />} onPress={checkMdm}>{checkBusy ? 'Checking…' : 'Check'}</Button></HStack>
        </HStack></Card.Header>
        <Card.Content><VStack gap={4}>
          {mdmCheck && <div className="mdm-check-panel" role="status">
            <Text as="span" variant="body-sm" weight="semibold">MDM recheck complete · {mdmCheck.mdm_summary.matched} accounts matched · {mdmCheck.mdm_summary.contracts_present} active contracts</Text>
            <Paragraph variant="body-sm" tone="secondary">Billing Account comes from Vendor Accounts. Contract status and dates come from Contracts, matched by account/Contract ID. Unmatched or ambiguous accounts remain blank.</Paragraph>
            <Table.Container><Table.Root variant="line" size="sm" density="comfortable">
              <Table.Header><Table.Row>{['Invoice', 'Vendor', 'Billing Account', 'Contract check', 'Contract Start Date', 'Contract End Date', 'Reason'].map((name) => <Table.Head key={name} scope="col">{name}</Table.Head>)}</Table.Row></Table.Header>
              <Table.Body>{shown.map(({ result, index }) => { const row = mdmCheck.rows[index] || {}; return <Table.Row key={`${result.source_file}-${index}-mdm`}>
                {['Invoice Number', 'Vendor -As per MDM', 'Billing Account', 'Contract check status', 'Contract Start Date', 'Contract End Date'].map((name) => <Table.Cell key={name}>{display(row[name])}</Table.Cell>)}
                <Table.Cell>{display(row['Billing Account match status'] === 'MATCHED' ? row['Contract check reason'] : row['Billing Account match reason'])}</Table.Cell>
              </Table.Row> })}</Table.Body>
            </Table.Root></Table.Container>
          </div>}
          <HStack gap={3} wrap align="end" justify="between">
            <Field.Root className="results-search"><Field.Label>Search invoices</Field.Label><Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search vendor, invoice number, or source…" /></Field.Root>
            <HStack gap={1} wrap aria-label="Filter invoice results">{[['all', 'All invoices'], ['success', 'Successful'], ['review', 'Needs review'], ['rejected', 'Rejected']].map(([key, label]) => <Button key={key} size="sm" variant={filter === key ? 'soft' : 'ghost'} tone={filter === key ? 'accent' : 'neutral'} aria-pressed={filter === key} onPress={() => setFilter(key)}>{label}</Button>)}</HStack>
          </HStack>
          <Tabs.Root value={view} onValueChange={setView} variant="line" size="sm">
            <Tabs.List aria-label="Invoice table view"><Tabs.Trigger value="overview">Overview</Tabs.Trigger><Tabs.Trigger value="full">All fields ({columns.length})</Tabs.Trigger><Tabs.Indicator /></Tabs.List>
            <Tabs.Content value="overview" inset="none">{view === 'overview' && table(overviewColumns)}</Tabs.Content>
            <Tabs.Content value="full" inset="none">{view === 'full' && table(columns, true)}</Tabs.Content>
          </Tabs.Root>
          {!shown.length && <Paragraph tone="muted" className="search-empty">No invoices match this search or filter.</Paragraph>}
          <HStack wrap gap={2} align="center"><Icon size="sm" tone="muted"><Artwork name="shield" /></Icon><Text as="span" variant="body-sm" tone="secondary">MDM matches the vendor and account, then checks contract dates and expiry. Expired contracts are rejected.</Text></HStack>
        </VStack></Card.Content>
        <Card.Footer><VStack gap={3}>
          <Text as="span" variant="body-sm" weight="semibold">Export this batch</Text>
          <HStack wrap gap={2}>{[['MDM/Invoice_data.csv', 'Invoice data CSV · successful only'], ['MDM/Contract_verified_invoices.csv', 'Contract-verified CSV'], ['Invoice_Data.csv', 'Full results CSV'], ['Invoice_Line_Items.csv', 'Service line items'], ['Audit_Report.csv', 'Audit report'], ['invoice_results.zip', 'Download all · ZIP']].map(([name, label]) => <DownloadButton key={name} path={`/batch/${batch.batch_id}/${name}`}>{label}</DownloadButton>)}</HStack>
        </VStack></Card.Footer>
      </Card.Root>
      <Collapsible.Root variant="plain"><Collapsible.Trigger>How validation and review work <Collapsible.Indicator /></Collapsible.Trigger><Collapsible.Content><Collapsible.ContentInner><VStack gap={2}>
        <Paragraph variant="body-sm" tone="secondary">Required fields: {requiredFields.join(', ')}. Missing service dates or an expired contract reject the invoice and exclude it from the approved Excel and contract-verified export. Other missing required fields, inconsistent amounts, duplicates, or unresolved MDM checks may require review. See All fields → Review reasons for the specific issue.</Paragraph>
        <Paragraph variant="body-sm" tone="secondary">Extraction completeness is the percentage of nine expected invoice fields that are filled; 100% means all are present, not that extraction accuracy has been independently verified. Region and source email remain blank if absent from the invoice; they are not invented.</Paragraph>
      </VStack></Collapsible.ContentInner></Collapsible.Content></Collapsible.Root>
    </VStack></Container>
  </Section>
}

function History({ history, reportFile, onRefresh, onOpen, onError }) {
  const [expanded, setExpanded] = useState(false)
  useEffect(() => { if (expanded && !history) onRefresh() }, [expanded, history, onRefresh])
  return <Collapsible.Root open={expanded} onOpenChange={setExpanded} variant="outline">
    <Collapsible.Trigger><HStack align="center" gap={3}><Icon size="md"><Artwork name="history" /></Icon><Text as="span" weight="semibold">Saved history & cumulative reports</Text></HStack><Collapsible.Indicator /></Collapsible.Trigger>
    <Collapsible.Content><Collapsible.ContentInner>
      <VStack gap={4}>
        <Paragraph tone="secondary">Saved invoices remain on this computer. Invoice_data.csv contains only successful invoices with a matched, active contract. Full results and audit exports retain rejected and review-needed invoices. Reset clears report rows while keeping saved corrections.</Paragraph>
        {reportFile && <Paragraph tone="secondary" style={{ overflowWrap: 'anywhere' }}>Active cumulative CSV: {reportFile}</Paragraph>}
        {history?.warnings?.map((warning, index) => <Paragraph key={index} tone="warning">{warning}</Paragraph>)}
        <HStack wrap gap={2}>
          <Button variant="soft" size="sm" onPress={async () => {
            try { await api('/history/refresh', { method: 'POST' }); onRefresh() }
            catch (error) { onError(error.message) }
          }}>Refresh reports</Button>
          {history?.report_files?.filter((name) => name !== 'Approved_Invoices.xlsx').map((name) => <DownloadButton key={name} path={`/history/${name}`}>{name}</DownloadButton>)}
        </HStack>
        {!history ? <Paragraph tone="muted" role="status">Loading saved reports…</Paragraph> : history.batches?.length ? <Table.Container><Table.Root variant="line" size="sm">
          <Table.Caption>Saved processing batches</Table.Caption>
          <Table.Header><Table.Row><Table.Head>Batch</Table.Head><Table.Head>Documents</Table.Head><Table.Head>Review needed</Table.Head><Table.Head>Source</Table.Head><Table.Head>Action</Table.Head></Table.Row></Table.Header>
          <Table.Body>{history.batches.map((batch) => <Table.Row key={batch.id}>
            <Table.Head scope="row">{batch.id.slice(0, 12)}</Table.Head><Table.Cell>{batch.counts.total}</Table.Cell>
            <Table.Cell>{batch.counts.review}</Table.Cell><Table.Cell>{batch.sources.join(', ')}</Table.Cell>
            <Table.Cell><Button size="sm" variant="ghost" onPress={() => onOpen(batch.id)}>Open batch</Button></Table.Cell>
          </Table.Row>)}</Table.Body></Table.Root></Table.Container> : <Paragraph tone="muted">No batches saved yet.</Paragraph>}
      </VStack>
    </Collapsible.ContentInner></Collapsible.Content>
  </Collapsible.Root>
}

export default function App() {
  const [active, setActive] = useState(window.location.hash.slice(1) || 'overview')
  const [sidebarState, setSidebarState] = useState(window.matchMedia('(max-width: 960px)').matches ? 'offcanvas' : 'expanded')
  const [config, setConfig] = useState(null)
  const [history, setHistory] = useState(null)
  const [batch, setBatch] = useState(null)
  const [files, setFiles] = useState([])
  const [rejected, setRejected] = useState([])
  const [threshold, setThreshold] = useState(95)
  const [tolerance, setTolerance] = useState(0.02)
  const [busy, setBusy] = useState(false)
  const [busyTask, setBusyTask] = useState(null)
  const [mdmBusy, setMdmBusy] = useState(false)
  const mdmPendingRef = useRef(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [runWarnings, setRunWarnings] = useState([])
  const [resetStep, setResetStep] = useState(0)
  const [resetToken, setResetToken] = useState(null)
  const [resetBusy, setResetBusy] = useState(false)
  const refreshConfig = async () => {
    const data = await api('/config')
    setConfig((previous) => {
      if (previous?.generation && previous.generation !== data.generation) setBatch(null)
      return data
    })
    return data
  }
  const refreshHistory = useCallback(async () => {
    try { setHistory(await api('/history')) }
    catch (err) { setError(err.message) }
  }, [])
  useEffect(() => {
    const breakpoint = window.matchMedia('(max-width: 960px)')
    const resize = (event) => setSidebarState(event.matches ? 'offcanvas' : 'expanded')
    const navigate = () => setActive(window.location.hash.slice(1) || 'overview')
    breakpoint.addEventListener('change', resize)
    window.addEventListener('hashchange', navigate)
    return () => { breakpoint.removeEventListener('change', resize); window.removeEventListener('hashchange', navigate) }
  }, [])
  const refreshCurrentBatch = async () => {
    if (!batch?.batch_id) return
    try { setBatch(await api(`/batches/${batch.batch_id}`)); setError('') }
    catch (err) { setError(err.message) }
  }
  const runMdm = async () => {
    if (!batch?.batch_id) return
    mdmPendingRef.current = true
    setMdmBusy(true); setError(''); setMessage(''); setRunWarnings([])
    try {
      const data = await withMinimumDisplayDelay(() => api('/mdm/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batch.batch_id, generation: batch.generation }),
      }))
      setBatch(data); setHistory(null); setRunWarnings(data.warnings || [])
      const summary = data.mdm_summary
      setMessage(`MDM matching complete: ${summary.matched} matched, ${summary.low_confidence} ambiguous, ${summary.not_found} not found. Select Check to verify contracts and see the detailed MDM summary. Saved CSV and Excel reports refreshed.`)
      await refreshConfig()
    } catch (err) { setError(err.message) }
    finally { mdmPendingRef.current = false; setMdmBusy(false) }
  }
  useEffect(() => {
    if (!batch?.batch_id) return undefined
    const reload = () => {
      if (document.visibilityState === 'visible' && !mdmPendingRef.current) {
        api(`/batches/${batch.batch_id}`).then(setBatch).catch((err) => setError(err.message))
      }
    }
    window.addEventListener('focus', reload)
    document.addEventListener('visibilitychange', reload)
    return () => { window.removeEventListener('focus', reload); document.removeEventListener('visibilitychange', reload) }
  }, [batch?.batch_id])
  useEffect(() => {
    refreshConfig().then((data) => { setThreshold(data.minimum_field_confidence); setTolerance(data.default_tolerance); setRunWarnings(data.warnings || []) }).catch((err) => setError(err.message))
  }, [])
  const processFiles = async () => {
    if (!files.length) return
    setBusyTask('upload')
    setBusy(true); setError(''); setMessage(''); setRunWarnings([])
    try {
      const body = new FormData()
      files.forEach((file) => body.append('files', file))
      body.append('tolerance', String(tolerance))
      body.append('threshold', String(threshold))
      const data = await api('/process', { method: 'POST', body })
      setBatch(data); setFiles([]); setHistory(null)
      setRunWarnings(data.warnings || [])
      setMessage(`Saved ${data.counts.total} invoice results. ${data.counts.review} need review; ${data.counts.rejected || 0} rejected; ${data.counts.failed} failed. Your local CSV and Excel reports are up to date.`)
      await refreshConfig()
      requestAnimationFrame(() => document.getElementById('results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    } catch (err) { setError(err.message) }
    finally { setBusy(false); setBusyTask(null) }
  }
  const saveLocations = async (payload) => {
    setError(''); setMessage(''); setRunWarnings([])
    const data = await api('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    setHistory(null); setRunWarnings(data.warnings || [])
    setThreshold(data.ui_settings.review_threshold); setTolerance(data.ui_settings.rounding_tolerance)
    setMessage(data.message)
    await refreshConfig()
    if (batch?.batch_id) await refreshCurrentBatch()
  }
  const runInputFolder = async () => {
    setBusyTask('input-folder'); setBusy(true); setError(''); setMessage(''); setRunWarnings([])
    try {
      const data = await api('/input-folder/run', { method: 'POST' })
      if (data.batch_id) setBatch(data)
      setHistory(null); setRunWarnings(data.warnings || [])
      setMessage(data.batch_id ? `Saved ${data.counts.total} results from your input folder. ${data.counts.review} need review; ${data.counts.rejected || 0} rejected; ${data.counts.failed} failed. Original files were kept.` : `No new supported files. ${data.already_processed} already processed; ${data.ignored_files} other entries ignored.`)
      await refreshConfig()
      if (data.batch_id) requestAnimationFrame(() => document.getElementById('results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    } catch (err) { setError(err.message) }
    finally { setBusy(false); setBusyTask(null) }
  }
  const runOutlook = async () => {
    setBusyTask('outlook')
    setBusy(true); setError(''); setMessage(''); setRunWarnings([])
    try {
      const data = await api('/outlook/run', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tolerance, threshold, source: 'desktop' }) })
      if (data.batch_id) setBatch(data)
      setRunWarnings(data.warnings || [])
      setHistory(null)
      setMessage(data.batch_id
        ? `Saved ${data.counts.total} results from ${data.desktop_emails_processed} classic Outlook emails; ${data.counts.failed} failed, ${data.counts.rejected || 0} rejected, ${data.counts.review} need review. ${data.emails_already_processed} emails already processed.`
        : data.emails_already_processed === 0 && data.ignored_files === 0 && !(data.warnings || []).length
          ? 'No supported invoice attachments were found in classic Outlook.'
          : `No new emails processed. ${data.emails_already_processed} already processed; ${data.ignored_files} messages had no supported attachments.`)
      await refreshConfig()
    } catch (err) { setError(err.message) }
    finally { setBusy(false); setBusyTask(null) }
  }
  const openBatch = async (id) => {
    try { setBatch(await api(`/batches/${id}`)); setMessage('Saved batch loaded.'); setError(''); window.scrollTo({ top: 0, behavior: 'smooth' }) }
    catch (err) { setError(err.message) }
  }
  const beginReset = async () => {
    try { setResetToken(await api('/reset/prepare', { method: 'POST' })); setResetStep(2) }
    catch (err) { setError(err.message); setResetStep(0) }
  }
  const confirmReset = async (event) => {
    event.preventDefault()
    setResetBusy(true)
    try {
      const data = await api('/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: resetToken.token, generation: resetToken.generation, confirmation: 'CLEAR SAVED INVOICES' }) })
      setBatch(null); setHistory(null); setFiles([]); setResetStep(0); setResetToken(null); setRunWarnings([])
      setMessage(`Reset complete: ${data.cleared_records} invoice rows cleared and ${data.deleted_files} uploaded files removed. ${data.retained_training_examples} saved corrections were kept.`); setError('')
      await refreshConfig()
    } catch (err) { setError(err.message); setResetStep(0) }
    finally { setResetBusy(false) }
  }
  return <>
    <Sidebar.Root state={sidebarState} onStateChange={setSidebarState} collapsedState="offcanvas" size="sm" position="sticky" surface="base" className="workspace-shell">
      <Sidebar.Panel className="workspace-sidebar" data-brick-appearance="dark" aria-label="Application sidebar">
        <Sidebar.Header><Brand /></Sidebar.Header>
        <Sidebar.Content><ScrollArea.Root className="navigation-scroll"><ScrollArea.Viewport><VStack gap={7}>
          <WorkspaceNavigation active={active} />
          <div className="sidebar-workflow"><VStack gap={3}>
            <Text as="span" variant="body-xs" weight="semibold" tone="muted">CONNECTED WORKFLOW</Text>
            {[['file', 'Read invoice documents'], ['layers', 'Match Vendor Accounts'], ['shield', 'Verify contract dates'], ['download', 'Save cumulative reports']].map(([icon, label]) => <HStack key={label} gap={3} align="center"><Icon size="sm" tone="muted"><Artwork name={icon} /></Icon><Text as="span" variant="body-sm" tone="secondary">{label}</Text></HStack>)}
          </VStack></div>
        </VStack></ScrollArea.Viewport></ScrollArea.Root></Sidebar.Content>
        <Sidebar.Footer><div className="privacy-card"><HStack gap={3} align="center">
          <span className="privacy-icon"><Icon size="md"><Artwork name="shield" /></Icon></span>
          <VStack gap={0}><Text as="span" variant="body-sm" weight="semibold">Local by design</Text><Text as="span" variant="body-xs" tone="muted">Your files stay on this device</Text></VStack>
        </HStack></div></Sidebar.Footer>
      </Sidebar.Panel>
      <Sidebar.Main>
        <AppBar.Root variant="surface" bordered className="workspace-topbar">
          <Container measure="max"><AppBar.Toolbar inset="none">
            <AppBar.Start><HStack align="center" gap={3}>
              <Sidebar.Trigger className="desktop-control" asChild><Button variant="ghost" size="sm" aria-label="Toggle sidebar" startIcon={<Artwork name="menu" />} /></Sidebar.Trigger>
              <span className="desktop-control"><Text as="span" variant="body-sm" tone="muted">WORKSPACE</Text></span>
              <span className="mobile-brand"><Brand compact /></span>
              <Text as="span" variant="body-sm" weight="semibold" className="desktop-control">Invoice operations</Text>
            </HStack></AppBar.Start>
            <AppBar.End><HStack gap={3} align="center">
              <Badge tone={!config ? 'neutral' : config.intake_ready ? 'success' : 'danger'}>{!config ? 'Connecting…' : config.intake_ready ? 'System ready' : 'Storage unavailable'}</Badge>
              {hostedMode && <Button size="sm" variant="ghost" onPress={disconnect}>Disconnect</Button>}
              <Button size="sm" variant="ghost" tone="danger" onPress={() => setResetStep(1)}>Reset data</Button>
            </HStack></AppBar.End>
          </AppBar.Toolbar></Container>
        </AppBar.Root>
        <div className="mobile-navigation"><Container measure="max"><HStack wrap gap={1}>
          {destinations.map(([id, label, icon]) => <Button key={id} href={`#${id}`} variant={active === id ? 'soft' : 'ghost'} tone={active === id ? 'accent' : 'neutral'} size="sm" startIcon={<Artwork name={icon} />}>{label}</Button>)}
        </HStack></Container></div>
        <Section id="overview" spacing="md" aria-labelledby="page-heading"><Container measure="max"><VStack gap={6}>
          <HStack justify="between" align="start" wrap gap={4}>
            <VStack gap={3} className="hero-copy"><Eyebrow>LESS ADMIN. MORE CLARITY.</Eyebrow>
              <Heading id="page-heading" level={1} variant="display-sm">Invoices in.<br /><span className="hero-accent">Clarity out.</span></Heading>
              <Paragraph variant="body-lg" tone="secondary">One workspace to extract invoice data, match your MDM records, and turn every batch into ready-to-use reports.</Paragraph>
            </VStack>
            <div className="hero-summary"><VStack gap={3}>
              <HStack gap={2} align="center"><span className="live-dot" /><Text as="span" variant="body-sm" weight="semibold">Your local workspace</Text></HStack>
              <HStack gap={6}><VStack gap={0}><Text as="span" variant="title-lg" weight="semibold">{config?.records ?? '—'}</Text><Text as="span" variant="body-sm" tone="secondary">Saved records</Text></VStack><VStack gap={0}><Text as="span" variant="title-lg" weight="semibold">{config?.batches ?? '—'}</Text><Text as="span" variant="body-sm" tone="secondary">Batches</Text></VStack></HStack>
              <Text as="span" variant="body-xs" tone="muted">Cumulative CSV & Excel · Stored on this computer</Text>
            </VStack></div>
          </HStack>
          <Grid.Root columns={{ initial: 2, md: 4 }} gap={3} className="workflow-strip">
            {[['01', 'upload', 'Collect', 'Files or Outlook attachments'], ['02', 'file', 'Extract', 'Local OCR & field extraction'], ['03', 'layers', 'Verify', 'Vendor, account & contract'], ['04', 'download', 'Export', 'Cumulative CSV & Excel']].map(([number, icon, title, detail]) => <HStack key={number} align="center" gap={3} className="workflow-step">
              <span className="step-icon"><Icon size="md"><Artwork name={icon} /></Icon></span>
              <VStack gap={0}><Text as="span" variant="body-sm" weight="semibold"><span className="step-number">{number}</span> {title}</Text><Text as="span" variant="body-xs" tone="secondary">{detail}</Text></VStack>
            </HStack>)}
          </Grid.Root>
          {(error || message || runWarnings.length > 0 || (config && (!config.api_ready || !config.storage_ready))) && <div className={`notification ${error || (config && !config.storage_ready) ? 'notification--error' : runWarnings.length || (config && !config.api_ready) ? 'notification--warning' : 'notification--success'}`} role={error ? 'alert' : 'status'} aria-live="polite"><HStack gap={3} align="start">
            <Icon size="md"><Artwork name={error || runWarnings.length ? 'alert' : 'check'} /></Icon>
            <VStack gap={1}>
              {error && <Paragraph tone="danger">{error}</Paragraph>}
              {message && <Paragraph>{message}</Paragraph>}
              {runWarnings.map((warning, index) => <Paragraph key={index} tone="warning">{warning}</Paragraph>)}
              {config && !config.api_ready && <Paragraph tone="warning">{config.setup_message || 'Automatic extraction is unavailable.'}</Paragraph>}
              {config && !config.storage_ready && <Paragraph tone="danger">Local storage is unavailable. Check LOCAL_STORAGE_DIR and folder permissions.</Paragraph>}
            </VStack>
          </HStack></div>}
          <Grid.Root columns={{ initial: 1, xl: 2 }} gap={5}>
            <Card.Root id="upload" variant="outline" size="lg" className="intake-card">
              <Card.Header><HStack gap={3} align="center"><span className="feature-icon"><Icon size="lg"><Artwork name="upload" /></Icon></span><VStack gap={1}><Card.Title as="h2">Upload invoices</Card.Title><Card.Description>A document, a batch, or an entire archive.</Card.Description></VStack></HStack></Card.Header>
              <Card.Content><VStack gap={4}>
                <FileUpload.Root aria-label="Invoice source files" files={files} onFilesChange={setFiles} onRejectedFilesChange={setRejected} multiple appendFiles accept=".pdf,.png,.jpg,.jpeg,.tiff,.webp,.bmp,.zip,.msg,.eml,.csv,.xlsx" maxFiles={100} maxSize={(config?.max_file_mb || 30) * 1000000} style={{ '--brick-file-upload-dropzone-min-block-size': '220px', '--brick-file-upload-background': '#f4faf9', '--brick-file-upload-border': '#bed9d5', '--brick-file-upload-radius': '14px' }}>
                  <FileUpload.HiddenInput aria-label="Select invoice source files" />
                  <FileUpload.Dropzone><VStack align="center" gap={3}>
                    <span className="dropzone-icon"><Icon size="xl"><Artwork name="upload" /></Icon></span>
                    <Text as="span" variant="title-sm" weight="semibold">Drop your files here</Text>
                    <Text as="span" variant="body-sm" tone="secondary">Up to {config?.max_file_mb || 30} MB per file · 100 files per batch</Text>
                    <FileUpload.Trigger>Browse files</FileUpload.Trigger>
                  </VStack></FileUpload.Dropzone>
                  {files.length > 0 && <FileUpload.ItemGroup>{files.map((file, index) => <FileUpload.Item key={`${file.name}-${index}`} file={file}><FileUpload.ItemName /><FileUpload.ItemSize /><FileUpload.ItemDeleteTrigger aria-label={`Remove ${file.name}`} /></FileUpload.Item>)}</FileUpload.ItemGroup>}
                </FileUpload.Root>
                <HStack wrap gap={2}>{['PDF', 'Images', 'ZIP', 'MSG / EML', 'CSV / XLSX'].map((format) => <Badge key={format} tone="neutral">{format}</Badge>)}</HStack>
                <Paragraph variant="body-sm" tone="secondary">Emails contribute only actual supported attachments—not their body or signature. CSV must be UTF-8; Excel must be XLSX.</Paragraph>
                {rejected.map((item, index) => <Paragraph key={index} tone="danger">{item.file?.name || 'File'}: {item.reason || 'File type, count or size was rejected'}</Paragraph>)}
                <div className="input-folder-card"><VStack gap={3}>
                  <Text as="span" variant="body-sm" weight="semibold">Or process files from a local folder</Text>
                  <Text as="span" variant="body-sm" tone="secondary" className="folder-path">{config?.ui_settings?.invoice_input_folder || 'No input folder configured. Manual upload is always available.'}</Text>
                  <HStack gap={3} wrap><Button variant="soft" onPress={runInputFolder} loading={busyTask === 'input-folder'} disabled={busy || mdmBusy || !config?.intake_ready || !config?.ui_settings?.invoice_input_folder}>Run input folder</Button><Button variant="ghost" href="#settings">Change locations</Button></HStack>
                  <Text as="span" variant="body-xs" tone="muted">Checks the folder’s top level. Already processed files are skipped; originals stay untouched.</Text>
                </VStack></div>
                {busyTask === 'upload' && <Progress.Root value={null}><Progress.Label>Extracting and validating invoices…</Progress.Label><Progress.Track><Progress.Indicator /></Progress.Track></Progress.Root>}
              </VStack></Card.Content>
              <Card.Footer><HStack gap={3} wrap justify="between" align="center">
                <Text as="span" variant="body-sm" tone="secondary">{files.length ? `${files.length} file${files.length === 1 ? '' : 's'} ready to process` : 'No files selected'}</Text>
                <Button size="lg" tone="accent" endIcon={<Artwork name="arrow" />} loading={busyTask === 'upload'} disabled={!files.length || !config?.intake_ready || busy} onPress={processFiles}>{files.length ? `Process ${files.length} file${files.length === 1 ? '' : 's'}` : 'Process invoices'}</Button>
              </HStack></Card.Footer>
            </Card.Root>
            <Card.Root id="outlook" variant="outline" size="lg" className="intake-card">
              <Card.Header><HStack gap={3} align="center"><span className="feature-icon feature-icon--blue"><Icon size="lg"><Artwork name="mail" /></Icon></span><VStack gap={1}><Card.Title as="h2">Bring your inbox into the flow</Card.Title><Card.Description>Invoice attachments, directly from classic Outlook.</Card.Description></VStack></HStack></Card.Header>
              <Card.Content><VStack gap={5}>
                <div className="outlook-folder"><HStack gap={3} align="center"><Icon size="lg" tone="info"><Artwork name="mail" /></Icon><VStack gap={1}>
                  <Text as="span" variant="body-xs" tone="secondary">OUTLOOK SOURCE FOLDER</Text><Text as="span" variant="title-md" weight="semibold">{config?.outlook_invoice_folder || 'Invoices'}</Text>
                  <Text as="span" variant="body-sm" tone="secondary">{config?.outlook_mailbox || 'The mailbox containing this folder'}</Text>
                </VStack></HStack></div>
                <VStack gap={3}>{['Retrieve actual, non-inline attachments', 'Skip previously processed messages', 'Mark successfully saved messages as read', 'Append results to your local CSV and Excel reports'].map((label) => <HStack key={label} gap={3} align="start"><Icon size="sm" tone="success"><Artwork name="check" /></Icon><Text as="span" variant="body-sm" tone="secondary">{label}</Text></HStack>)}</VStack>
                <Paragraph variant="body-sm" tone="muted">Classic Outlook must be available on this computer. Original emails stay in Outlook.</Paragraph>
                {busyTask === 'outlook' && <Progress.Root value={null}><Progress.Label>Reading Outlook and processing attachments…</Progress.Label><Progress.Track><Progress.Indicator /></Progress.Track></Progress.Root>}
              </VStack></Card.Content>
              <Card.Footer><Button size="lg" tone="accent" variant="soft" startIcon={<Artwork name="mail" />} endIcon={<Artwork name="arrow" />} loading={busyTask === 'outlook'} disabled={busy || !config?.intake_ready} onPress={runOutlook}>Run Outlook</Button></Card.Footer>
            </Card.Root>
          </Grid.Root>
          <LocationSettings saved={config?.ui_settings} threshold={threshold} tolerance={tolerance} setThreshold={setThreshold} setTolerance={setTolerance} disabled={busy || mdmBusy || resetBusy} model={config?.model} examples={config?.reviewed_training_examples} onSave={saveLocations} onError={setError} />
        </VStack></Container></Section>
        <Results batch={batch} columns={config?.mdm_columns || []} requiredFields={config?.required_fields || []} tolerance={tolerance} threshold={threshold} onSaved={(data) => { setBatch(data); setHistory(null); setMessage('Correction saved and invoice revalidated.'); setRunWarnings(data.warnings || []); refreshConfig().catch((err) => setError(err.message)) }} onRefresh={refreshCurrentBatch} onRunMdm={runMdm} mdmBusy={mdmBusy} onError={setError} />
        <Section id="history" spacing="md" aria-label="Reports and history"><Container measure="max"><VStack gap={4}>
          <History history={history} reportFile={config?.cumulative_invoice_report_file} onRefresh={refreshHistory} onOpen={openBatch} onError={setError} />
          {(config?.records ?? 0) > 0 && <HStack gap={2} wrap><DownloadButton path="/history/MDM/Invoice_data.csv">Cumulative invoice CSV</DownloadButton><DownloadButton path="/history/MDM/Contract_verified_invoices.csv">Contract-verified CSV</DownloadButton></HStack>}
          <HStack justify="between" wrap gap={2} className="workspace-footer"><Text as="span" variant="body-xs" tone="muted">InvoiceIQ · Intelligent workflow orchestration</Text><HStack gap={2} align="center"><Icon size="xs" tone="muted"><Artwork name="shield" /></Icon><Text as="span" variant="body-xs" tone="muted">Locally processed. Transparently validated.</Text></HStack></HStack>
        </VStack></Container></Section>
      </Sidebar.Main>
    </Sidebar.Root>
    <AlertDialog.Root open={resetStep === 1} onOpenChange={(open) => !open && setResetStep(0)}>
      <AlertDialog.Portal><AlertDialog.Overlay /><AlertDialog.Content>
        <AlertDialog.Header><AlertDialog.Title>Are you sure?</AlertDialog.Title><AlertDialog.Description>Reset will clear saved invoice rows and uploaded files. Your trained models and reviewed training examples will stay. Continue to the final confirmation?</AlertDialog.Description></AlertDialog.Header>
        <AlertDialog.Footer><AlertDialog.Cancel asChild><Button variant="outline" onPress={() => setResetStep(0)}>No, keep data</Button></AlertDialog.Cancel>
          <AlertDialog.Action asChild><Button tone="warning" onPress={beginReset}>Yes, continue</Button></AlertDialog.Action></AlertDialog.Footer>
      </AlertDialog.Content></AlertDialog.Portal>
    </AlertDialog.Root>
    <AlertDialog.Root open={resetStep === 2} onOpenChange={(open) => !open && setResetStep(0)}>
      <AlertDialog.Portal><AlertDialog.Overlay /><AlertDialog.Content>
        <AlertDialog.Header><AlertDialog.Title>Clearing invoices — final confirmation</AlertDialog.Title><AlertDialog.Description>Step 2 of 2: Remove uploaded invoices, Outlook email files and saved invoice rows? CSV and Excel reports will keep their headers but contain no invoice rows. Trained models and reviewed examples remain.</AlertDialog.Description></AlertDialog.Header>
        <AlertDialog.Body><Paragraph tone="secondary">This cannot be undone in the app. Close Excel and other running copies first. Code, API configuration and files outside invoice intake are not deleted.</Paragraph></AlertDialog.Body>
        <AlertDialog.Footer><AlertDialog.Cancel asChild><Button variant="outline" onPress={() => setResetStep(0)}>No, cancel</Button></AlertDialog.Cancel>
          <AlertDialog.Action asChild><Button tone="danger" loading={resetBusy} onClick={confirmReset}>Yes, clear invoice rows</Button></AlertDialog.Action></AlertDialog.Footer>
      </AlertDialog.Content></AlertDialog.Portal>
    </AlertDialog.Root>
  </>
}
