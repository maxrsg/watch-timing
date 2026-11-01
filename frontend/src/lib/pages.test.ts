import { describe, expect, it } from 'vitest'
import { pageFor, parseHash, savedMeasurementFor, watchHash, watchIdFor } from './pages'

describe('pageFor', () => {
  it('finds pages by the hash before any path or query', () => {
    expect(pageFor('#watches').hash).toBe('#watches')
    expect(pageFor('#watches/3').hash).toBe('#watches')
    expect(pageFor('#watches?owner=x').hash).toBe('#watches')
  })

  it('sends unknown hashes to the start page', () => {
    expect(pageFor('').hash).toBe('')
    expect(pageFor('#').hash).toBe('')
    expect(pageFor('#nope/1').hash).toBe('')
    expect(pageFor('#clock').hash).toBe('')
    expect(pageFor('#probe').hash).toBe('')
  })
})

describe('watchIdFor', () => {
  it('reads the watch id', () => {
    expect(watchIdFor(watchHash(12))).toBe(12)
    expect(watchIdFor(watchHash(12, 5))).toBe(12)
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

describe('savedMeasurementFor', () => {
  it('reads the saved measurement on a watch page', () => {
    expect(savedMeasurementFor(watchHash(3, 7))).toBe(7)
  })

  it('is null without one, off a watch page, or for anything that is not an id', () => {
    expect(savedMeasurementFor(watchHash(3))).toBeNull()
    expect(savedMeasurementFor('#watches?saved=7')).toBeNull()
    expect(savedMeasurementFor('#watches/3?saved=x')).toBeNull()
    expect(savedMeasurementFor('#watches/3?saved=0')).toBeNull()
  })
})
