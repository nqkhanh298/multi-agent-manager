import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

const token = process.env.M5_LIVE_TOKEN

test('creates a real run and displays its source, tests and artifact', async ({ page }) => {
  test.skip(!token, 'M5_LIVE_TOKEN is required for the live backend check')
  test.setTimeout(100_000)
  await page.addInitScript((value) => sessionStorage.setItem('m5-api-token', value), token!)
  await page.goto('/')
  await expect(page.getByText('API kết nối')).toBeVisible()
  await page.getByRole('button', { name: 'Tạo dự án' }).click()
  await page.getByRole('textbox', { name: 'Tên dự án mới' }).fill(`M5 Live ${Date.now()}`)
  await page.getByRole('textbox', { name: 'Tên dự án mới' }).press('Enter')
  await page.getByLabel('Bạn muốn hệ thống xây gì?').fill('Xây ứng dụng quản lý công việc')
  await page.getByRole('button', { name: /Bắt đầu chạy/ }).click()
  await expect(page.getByText('Backend Dev').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Hoàn thành', { exact: true }).first()).toBeVisible({ timeout: 70_000 })
  await expect(page.getByRole('button', { name: /Tải mã nguồn/ })).toBeEnabled()
  await page.getByRole('tab', { name: /Code/ }).click()
  await expect(page.getByRole('button', { name: 'backend.py', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'backend.py', exact: true }).click()
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
  await page.getByRole('tab', { name: /Diff/ }).click()
  await expect(page.locator('.diff-add').first()).toBeVisible()
  await page.getByRole('tab', { name: /Tests/ }).click()
  await expect(page.locator('.terminal-output')).toContainText('4 passed')
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: resolve('../../.local/m5-dashboard.png'), fullPage: true })
})
