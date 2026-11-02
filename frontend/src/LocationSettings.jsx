import React, { useEffect, useState } from 'react'
import { Badge, Button, Collapsible, Field, Grid, HStack, Input, NumberInput, Paragraph, Text, VStack } from '@flowstack-ui/brick'
import { locationFields, settingsError, settingsPayload } from './settings-fields.js'

export default function LocationSettings({ saved, threshold, tolerance, setThreshold, setTolerance, disabled, model, examples, onSave, onError }) {
  const [draft, setDraft] = useState({})
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(window.location.hash === '#settings')
  useEffect(() => {
    const reveal = () => { if (window.location.hash === '#settings') setOpen(true) }
    window.addEventListener('hashchange', reveal)
    return () => window.removeEventListener('hashchange', reveal)
  }, [])
  useEffect(() => { if (saved) setDraft(saved) }, [saved?.revision, saved?.output_folder, saved?.mdm_folder])
  const submit = async (event) => {
    event.preventDefault()
    const payload = settingsPayload(draft, threshold, tolerance)
    const issue = settingsError(payload)
    if (issue) { onError(issue); return }
    setSaving(true)
    try {
      const persisted = await onSave(payload)
      if (persisted) setDraft(persisted)
    }
    catch (error) { onError(error.message) }
    finally { setSaving(false) }
  }
  return <Collapsible.Root id="settings" open={open} onOpenChange={setOpen} variant="outline" className="location-settings">
    <Collapsible.Trigger><HStack gap={3} align="center"><Text as="span" weight="semibold">Settings</Text><span className="settings-hint"><Text as="span" variant="body-sm" tone="muted">Folders, reports & validation</Text></span></HStack><Collapsible.Indicator /></Collapsible.Trigger>
    <Collapsible.Content><Collapsible.ContentInner>
      <form onSubmit={submit}><VStack gap={5}>
        <Paragraph variant="body-sm" tone="secondary">Paste absolute folder paths on the computer running this app. Save settings to use them for future runs. Your saved history stays in place.</Paragraph>
        <Grid.Root columns={{ initial: 1, md: 2 }} gap={5}>
          {locationFields.map(([key, label, placeholder, description]) => <Field.Root key={key}>
            <Field.Label htmlFor={`setting-${key}`}>{label}</Field.Label>
            <Input id={`setting-${key}`} name={key} value={draft[key] || ''} placeholder={placeholder} disabled={disabled || saving || !saved} onChange={(event) => setDraft((previous) => ({ ...previous, [key]: event.target.value }))} />
            <Field.Description>{description}</Field.Description>
          </Field.Root>)}
          <Field.Root><Field.Label>Review threshold (%)</Field.Label><NumberInput.Root value={threshold} onValueChange={(value) => setThreshold(value ?? 95)} min={1} max={100} step={1} disabled={disabled || saving}><NumberInput.Input name="threshold" /><NumberInput.Decrement aria-label="Decrease threshold" /><NumberInput.Increment aria-label="Increase threshold" /></NumberInput.Root><Field.Description>Uses calibrated confidence when available. A lower threshold does not fix missing service dates, duplicates, or MDM validation issues.</Field.Description></Field.Root>
          <Field.Root><Field.Label>Rounding tolerance</Field.Label><NumberInput.Root value={tolerance} onValueChange={(value) => setTolerance(value ?? 0)} min={0} max={100} step={0.01} precision={2} disabled={disabled || saving}><NumberInput.Input name="tolerance" /><NumberInput.Decrement aria-label="Decrease tolerance" /><NumberInput.Increment aria-label="Increase tolerance" /></NumberInput.Root><Field.Description>Allowed amount difference during validation. Applies to the next batch.</Field.Description></Field.Root>
        </Grid.Root>
        <HStack justify="between" align="center" wrap gap={3}>
          <VStack gap={1}><Text as="span" variant="body-sm" weight="semibold">{model || 'Local extraction engine'}</Text><Badge tone="info">{examples ?? 0} saved corrections</Badge></VStack>
          <Button type="submit" tone="accent" size="lg" loading={saving} disabled={disabled || !saved}>Save settings</Button>
        </HStack>
      </VStack></form>
    </Collapsible.ContentInner></Collapsible.Content>
  </Collapsible.Root>
}
