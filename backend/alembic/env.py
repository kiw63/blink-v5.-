from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config,pool
from app.config import settings
from app.db import Base
from app import models
config=context.config
config.set_main_option('sqlalchemy.url',settings.database_url)
if config.config_file_name:fileConfig(config.config_file_name)
target_metadata=Base.metadata

def online():
    engine=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()

if context.is_offline_mode():
    context.configure(url=settings.database_url,target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
else:online()
