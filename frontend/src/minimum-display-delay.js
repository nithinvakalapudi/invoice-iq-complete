// Run work immediately, but keep its result hidden for a short, predictable interval.
export async function withMinimumDisplayDelay(request, milliseconds = 4000) {
  const [result] = await Promise.all([
    request(),
    new Promise((resolve) => setTimeout(resolve, milliseconds)),
  ])
  return result
}
