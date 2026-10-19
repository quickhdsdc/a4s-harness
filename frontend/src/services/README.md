# Frontend Services Layer

This directory contains all API service modules for the AAS Submodel Creator frontend.

## Architecture

```
services/
├── api.ts              # Base HTTP client (fetch wrapper)
├── aasService.ts       # AAS-related API calls
├── fileService.ts      # File upload/download operations
└── websocketService.ts # WebSocket connection management
```

## Base API Client (`api.ts`)

The base API client provides a centralized HTTP client with:
- ✅ Automatic base URL from environment store
- ✅ Request/response error handling
- ✅ Timeout support (default: 30s)
- ✅ Query parameter builder
- ✅ TypeScript types
- ✅ Automatic JSON parsing
- ✅ FormData support
- ✅ File download support

### Usage

```typescript
import { api } from '@/services/api'

// GET request
const response = await api.get('/api/templates')
console.log(response.data)

// GET with query parameters
const response = await api.get('/api/check-extraction/:filename', {
  params: { filename: 'motor.pdf' }
})

// POST request
const response = await api.post('/api/save-edited-entities', {
  original_filename: 'motor.pdf',
  entities: [...]
})

// POST with FormData (file upload)
const formData = new FormData()
formData.append('file', file)
const response = await api.post('/api/upload', formData)

// File download
const blob = await api.downloadFile('/api/download/aasx/MyAAS')
```

### Error Handling

The API client throws `ApiError` instances with structured error information:

```typescript
import { ApiError } from '@/services/api'

try {
  const response = await api.get('/api/some-endpoint')
} catch (error) {
  if (error instanceof ApiError) {
    console.error('API Error:', error.status, error.message)
    console.error('Response data:', error.data)
  }
}
```

### Configuration

```typescript
// Set custom header
api.setHeader('Authorization', 'Bearer token')

// Remove header
api.removeHeader('Authorization')

// Custom timeout (per request)
const response = await api.get('/api/slow-endpoint', {
  timeout: 60000 // 60 seconds
})
```

## Service Modules

### `aasService.ts` - AAS Operations

Handles all AAS-related operations with full TypeScript support.

**Available Methods:**
```typescript
import { aasService } from '@/services/aasService'

// Check if extraction exists
const { exists, filename } = await aasService.checkExtraction('motor.pdf')

// Check if AAS exists on server
const { exists, id } = await aasService.checkAAS('MyAAS', 'http://localhost:8081')

// Get extracted entities
const { entities, count } = await aasService.getExtractedEntities('motor.json')

// Save edited entities
const result = await aasService.saveEditedEntities({
  original_filename: 'motor.pdf',
  entities: [{ name: 'Power', value: '2.5kW', description: 'Motor power' }]
})

// Check if matching results exist
const { exists } = await aasService.checkMatching('motor.pdf')

// Get matching results
const { results } = await aasService.getMatchingResults('motor_match.json')

// Save matching results
await aasService.saveMatchingResults({
  filename: 'motor.pdf',
  results: [/* matching data */]
})

// Get AAS properties for dropdown
const { properties, grouped } = await aasService.getAASProperties('MyAAS')

// Download AAS as AASX
const blob = await aasService.downloadAASX('MyAAS', 'http://localhost:8081')
aasService.triggerDownload(blob, 'MyAAS.aasx')

// Download AAS as JSON
const blob = await aasService.downloadJSON('MyAAS')
aasService.triggerDownload(blob, 'MyAAS.json')
```

### `fileService.ts` - File Operations

Handles file upload/download and template operations.

**Available Methods:**
```typescript
import { fileService } from '@/services/fileService'

// Get available templates
const templates = await fileService.getTemplates('http://localhost:8081')
// Returns: [{ id, name, idShort, description }, ...]

// Upload a file
const result = await fileService.uploadFile(file)
// Returns: { success, filename, path, size }

// Validate file before upload
const { valid, error } = fileService.validateFile(file, {
  maxSize: 10 * 1024 * 1024, // 10MB
  allowedTypes: ['application/pdf']
})

// Format file size for display
const sizeStr = fileService.formatFileSize(2048576) // "2.0 MB"
```

### `websocketService.ts` - WebSocket Management

Manages WebSocket connections for real-time chat with the MCP agent.

**Usage as Composable:**
```typescript
import { useWebSocket } from '@/services/websocketService'

export default {
  setup() {
    const { connectionStatus, isConnected, connect, disconnect, send, onMessage } = useWebSocket()

    // Connect on mount
    onMounted(() => {
      connect()
    })

    // Disconnect on unmount
    onUnmounted(() => {
      disconnect()
    })

    // Listen for messages
    const unsubscribe = onMessage((data) => {
      console.log('Received:', data.type, data.content)

      if (data.type === 'assistant_message') {
        // Handle assistant response
      }
    })

    // Send a message
    const sendMessage = () => {
      send({
        message: 'Extract data from motor.pdf',
        file_context: { name: 'motor.pdf', path: './Attachments/motor.pdf' },
        wizard_context: {
          selectedTemplates: ['TechnicalData'],
          aasServerEndpoint: 'http://localhost:8081',
          targetAAS: 'MyAAS',
          dataSourceType: 'pdf',
          editedEntitiesFile: null
        }
      })
    }

    return { connectionStatus, isConnected, sendMessage }
  }
}
```

**Using Shared Instance (Recommended):**
```typescript
import { useSharedWebSocket } from '@/services/websocketService'

// Multiple components can share the same WebSocket connection
const ws = useSharedWebSocket()
```

**Helper Functions:**
```typescript
import { buildChatMessage } from '@/services/websocketService'

// Build message with contexts
const message = buildChatMessage(
  'Extract data from PDF',
  { name: 'motor.pdf', path: './Attachments/motor.pdf' },
  { selectedTemplates: ['TechnicalData'], ... }
)

ws.send(message)
```

## Best Practices

1. **Always use services in components** - Never call `fetch()` directly
2. **Handle errors properly** - Use try/catch with ApiError
3. **Use TypeScript types** - Define request/response interfaces
4. **Keep services focused** - Each service handles one domain
5. **Centralize configuration** - Use environment store for URLs

## Migration Guide

**Before (component with inline fetch):**
```vue
<script setup>
const fetchData = async () => {
  const response = await fetch('http://localhost:8000/api/templates')
  const data = await response.json()
  return data
}
</script>
```

**After (component using service):**
```vue
<script setup>
import { getTemplates } from '@/services/fileService'

const fetchData = async () => {
  const response = await getTemplates()
  return response.data
}
</script>
```
