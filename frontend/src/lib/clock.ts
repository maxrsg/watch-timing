import { getServerTime } from '@/api/client'

/** Device clock vs server clock. Positive offset = server is ahead of the device. */
export type ClockSample = { offsetMs: number; rttMs: number }

/** NTP-style estimate from one round trip; uncertainty is ± rtt/2. */
export function sampleFromRoundTrip(sentMs: number, serverMs: number, receivedMs: number): ClockSample {
  return { offsetMs: serverMs - (sentMs + receivedMs) / 2, rttMs: receivedMs - sentMs }
}

/** Several round trips; the one with the shortest round trip is the most accurate. */
export async function measureClockOffset(rounds = 5): Promise<ClockSample> {
  const samples: ClockSample[] = []
  for (let i = 0; i < rounds; i++) {
    const sent = Date.now()
    const server = await getServerTime()
    samples.push(sampleFromRoundTrip(sent, Date.parse(server.server_time_utc), Date.now()))
  }
  return samples.reduce((best, s) => (s.rttMs < best.rttMs ? s : best))
}
