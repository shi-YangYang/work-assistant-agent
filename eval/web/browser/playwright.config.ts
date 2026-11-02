import { defineConfig } from '@playwright/test'
import base from '../../../apps/web/playwright.config'
export default defineConfig({ ...base, testDir: __dirname })
