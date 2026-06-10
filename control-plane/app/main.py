from app.database import get_db
from app.middleware import TenantIsolationMiddleware
from app.models import Brand
from fastapi import Depends, FastAPI, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

app = FastAPI(title="Agency OS Control Plane", version="1.0.0")

# Register strict security isolation middleware
app.add_middleware(TenantIsolationMiddleware)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
  """System health check endpoint."""
  return {"status": "healthy", "service": "control-plane"}


@app.get("/brands", response_model=list[dict])
async def list_brands(db: AsyncSession = Depends(get_db)):
  """Fetches all brands matching the tenant ID evaluated dynamically via

  PostgreSQL RLS.
  """
  stmt = select(Brand)
  result = await db.execute(stmt)
  brands = result.scalars().all()
  return [
      {"id": b.id, "name": b.name, "created_at": b.created_at} for b in brands
  ]
