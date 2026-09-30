import { beforeEach } from 'vitest'
import { clearQueryResources } from '../../apps/web/src/lib/query-resource'

// Each test represents a separate browser lifetime unless it explicitly tests reuse.
beforeEach(() => clearQueryResources())
