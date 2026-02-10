# Distributed Cloud File Storage System (Google Drive–Like Backend)

A backend-focused, distributed file storage system inspired by Google Drive, built to demonstrate **real-world backend engineering and distributed systems design**.

This project goes beyond CRUD APIs by implementing **chunked storage, replication, consistent hashing, file versioning, and collaborative sharing with RBAC**, all while maintaining a clean separation between control-plane and data-plane responsibilities.

> **Primary goal:** Build a scalable, fault-tolerant file storage backend from first principles, suitable for large-file handling and collaborative workflows.

---

## 🚀 Key Features

### Core Storage
- Chunked file uploads with configurable chunk size
- Multi-node replication with configurable replication factor
- Deterministic chunk placement using **consistent hashing**
- Failure-aware streaming downloads with replica fallback

### File Management
- Files treated as logical identities
- Immutable file versions (no overwrites)
- Download latest or specific file versions
- Safe deletion rules (prevent destructive operations)

### Collaboration & Security
- Role-Based Access Control (RBAC):
  - `owner`, `write`, `read`
- Google Drive–like sharing semantics
- Centralized permission enforcement
- Shared files and shared-by-me listings

### Architecture & Infra
- Control plane + data plane separation
- Dockerized multi-node simulation
- PostgreSQL-backed metadata store
- Alembic migrations for schema evolution

---

## 🧠 High-Level Architecture

The system is split into two logical layers:

### Control Plane (Main API)
Responsible for:
- Users, folders, files
- File versions and metadata
- Chunk placement and replication decisions
- Permissions and sharing
- Download orchestration and failover

**Tech:** FastAPI + PostgreSQL

### Data Plane (Storage Nodes)
- Stateless FastAPI services
- Store raw chunk bytes on disk
- Expose minimal HTTP contract:
  - `PUT /chunks/{chunk_id}`
  - `GET /chunks/{chunk_id}`

Multiple storage nodes run in parallel to simulate a distributed cluster.

📐 See **ARCHITECTURE.md** for a detailed design walkthrough.

---

## 📦 Data Model Overview

### Files (Logical Identity)
* id
* name
* owner_id
* folder_id

### File Versions (Immutable Snapshots)
* id
* file_id
* version_number
* size_bytes
* created_at

### Chunks (Physical Storage Units)
* id (UUID)
* file_version_id
* index
* size_bytes

### Chunk Locations (Replication Mapping)
* chunk_id
* node_id

### Permissions (RBAC)
* file_id
* user_id
* role (owner | write | read)


---

## 🔀 Consistent Hashing

- Storage nodes are placed on a hash ring
- Each chunk ID is hashed onto the ring
- The first node clockwise is the primary replica
- The next `R-1` nodes serve as replicas

This ensures:
- Deterministic placement
- Minimal data movement when nodes are added/removed
- Scalable and predictable distribution

---

## 📤 Upload & Versioning Flow

### Create New File
`POST /files/upload`

- Creates file
- Assigns owner permission
- Creates version 1
- Splits content into chunks
- Replicates chunks across nodes

### Upload New Version
`POST /files/{file_id}/versions`

- Requires `write` permission
- Creates new immutable version
- Old versions remain intact

---

## 📥 Download Flow

`GET /files/{file_id}/download`  
`GET /files/{file_id}/download?version=N`

1. Resolve file and requested version
2. Fetch ordered chunks
3. For each chunk:
   - Try replicas in order
   - Skip offline or failing nodes
4. Stream data sequentially to client

---

## 🔐 Sharing & Permissions

- Files have exactly one owner
- Shared users operate on the same underlying file
- Uploading a new version is an edit operation
- Permissions enforced centrally via service layer

| Action | Read | Write | Owner |
|------|------|------|------|
| Download | ✅ | ✅ | ✅ |
| Upload new version | ❌ | ✅ | ✅ |
| Share file | ❌ | ❌ | ✅ |
| Delete file | ❌ | ❌ | ✅ |

---

## 🔧 Configuration

### Environment variables:

  DATABASE_URL=postgresql://user:pass@db:5432/storage
  
  CHUNK_SIZE_BYTES=4194304
  
  REPLICATION_FACTOR=2
  
  CORS_ORIGINS=["http://localhost:5173"]

## 🐳 Running Locally

### Prerequisites
- Docker
- Docker Compose

### Start the system
```bash
docker compose up --build
```

Although storage nodes are Dockerized services, the design supports:
- S3
- MinIO

After spinning the backend up, head over to the frontend readme via [Cloud_drive_frontend]([https://github.com](https://github.com/Saanimustapha/Distributed-Cloud-File-Storage-System-Frontend-/tree/main/cloud-drive-frontend))




