import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/zoo"
    
    # Feature flags for Bug Zoo
    # Bug 1: Check-then-act race on the idempotency key (SELECT then INSERT)
    bug_1_race_condition: bool = False
    
    # Bug 2: No idempotency handling, so a duplicate POST creates two rows
    bug_2_no_idempotency: bool = False
    
    # Bug 3: Missing unique constraint on the key column
    bug_3_missing_unique_constraint: bool = False
    
    # Bug 4: Key not scoped to user or endpoint, so one user's key replays another's response
    bug_4_unscoped_key: bool = False

settings = Settings()
