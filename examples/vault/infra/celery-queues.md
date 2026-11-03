# Celery queues
Three queues: default, matcher (concurrency 2), exports. Broker and result backend are Redis.
Visibility timeout raised to 3600s after long DATEV exports got redelivered.
