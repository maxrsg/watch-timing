import { describe, expect, it } from 'vitest'
import { pageFor, parseHash, watchHash, watchIdFor } from './pages'

describe('pageFor', () => {
  it('finds pages by the hash before any path or query', () => {
    expect(pageFor('#watches').hash).toBe('#watches')
    expect(pageFor('#watches/3').hash).toBe('#watches')
    expect(pageFor('#watches?owner=x').hash).toBe('#watches')
    expect(pageFor('#clock').hash).toBe('#clock')
  })

  it('sends unknown hashes to the start page', () => {
    expect(pageFor('').hash).toBe('')
    expect(pageFor('#').hash).toBe('')
    expect(pageFor('#nope/1').hash).toBe('')
  })
})

describe('watchIdFor', () => {
  it('reads the watch id', () => {
    expect(watchIdFor(watchHash(12))).toBe(12)
    expect(watchIdFor('#watches/12?x=1')).toBe(12)
  })

  it('is null for the list and for anything that is not an id', () => {
    expect(watchIdFor('#watches')).toBeNull()
    expect(watchIdFor('#watches/abc')).toBeNull()
    expect(watchIdFor('#watches/0')).toBeNull()
    expect(watchIdFor('#probe/3')).toBeNull()
  })
})

it('parses the query', () => {
  expect(parseHash('#watches?owner=abc').query.get('owner')).toBe('abc')
})
