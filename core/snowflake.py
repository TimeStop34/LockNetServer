import asyncio

from snowflakekit import SnowflakeGenerator, SnowflakeConfig

CUSTOM_EPOCH = 1767225600000

config = SnowflakeConfig(
    epoch=CUSTOM_EPOCH,
    node_id=1,
    worker_id=0,
    time_bits=41,
    node_bits=10,
    worker_bits=0,
)

generator = SnowflakeGenerator(config=config)