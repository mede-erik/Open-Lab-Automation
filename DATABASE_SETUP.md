# Database Integration Requirements

This file lists the required dependencies for PostgreSQL/TimescaleDB integration.

## Required Python Packages

Install the following packages using pip:

```bash
pip install psycopg2-binary
```

Or for development with headers:

```bash
pip install psycopg2
```

## PostgreSQL Setup

You need a PostgreSQL instance with TimescaleDB extension installed.

### Using Docker (Recommended for development)

```bash
# Pull and run TimescaleDB Docker image
docker run -d --name timescaledb -p 5432:5432 -e POSTGRES_PASSWORD=mypassword timescale/timescaledb:latest-pg14

# Create application database and user
docker exec -it timescaledb psql -U postgres -c "CREATE USER dcdc_app WITH PASSWORD 'your_password';"
docker exec -it timescaledb psql -U postgres -c "CREATE DATABASE dcdc_measurements OWNER dcdc_app;"
```

### Manual PostgreSQL Installation

1. Install PostgreSQL 14+ on your system
2. Install TimescaleDB extension
3. Create database and user as shown above

## Application Configuration

1. Launch the application
2. Go to Settings → Database Configuration
3. Configure connection parameters:
   - Host: localhost
   - Port: 5432
   - Database: dcdc_measurements
   - Username: dcdc_app
   - Password: your_password
4. Test connection
5. Initialize schema

## Features

The database integration provides:

- **Project Management**: Store project metadata in PostgreSQL
- **Measurement Data**: Efficiently store scalar measurement data
- **Waveform Data**: High-performance time-series storage using TimescaleDB hypertables
- **Query Performance**: Optimized indexes and TimescaleDB functions
- **Data Analysis**: Complex queries for efficiency mapping and waveform analysis
- **Bulk Operations**: Efficient bulk insert for waveform data

## Database Schema

The system creates the following tables:

1. **progetti**: Project metadata and global parameters
2. **sessioni_sweep**: Measurement sweep sessions with target parameters
3. **punti_misura**: Individual measurement points with scalar data
4. **forme_d_onda**: Time-series waveform data (TimescaleDB hypertable)

All tables include proper foreign key relationships with CASCADE deletion
and optimized indexes for query performance.