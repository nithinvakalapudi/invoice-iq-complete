export const hostedMode = import.meta.env?.MODE === 'hosted'
export const localOrigin = 'http://127.0.0.1:8505'
const connectionKey = 'invoice-iq-local-connection'

export const connectedToken = () => window.sessionStorage.getItem(connectionKey) || ''
export const saveConnection = (token) => window.sessionStorage.setItem(connectionKey, token)
export const disconnect = () => {
  window.sessionStorage.removeItem(connectionKey)
  window.location.reload()
}

const request = (path, options = {}) => {
  const token = hostedMode ? connectedToken() : ''
  if (hostedMode && !token) throw new Error('Connect this computer to process invoices.')
  const headers = new Headers(options.headers)
  if (hostedMode) headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${hostedMode ? localOrigin : ''}/api${path}`, {
    cache: 'no-store', ...options, headers,
  })
}

const checkedResponse = async (response) => {
  if (response.ok) return response
  let message = `${response.status} ${response.statusText}`
  try {
    const body = await response.json()
    message = typeof body.detail === 'string' ? body.detail : message
  } catch { /* Keep the HTTP status if the response has no JSON detail. */ }
  throw new Error(message)
}

export const api = async (path, options = {}) =>
  (await checkedResponse(await request(path, options))).json()

export async function downloadReport(path) {
  const response = await checkedResponse(await request(`/download${path}`))
  const blobUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = blobUrl
  const disposition = response.headers.get('Content-Disposition') || ''
  link.download = disposition.match(/filename="([^"]+)"/i)?.[1]
    || decodeURIComponent(path.split('/').pop() || 'report')
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60000)
}
