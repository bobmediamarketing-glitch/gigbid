# Sales research agent for a media client

**Date:** 2024-11-15  
**Client industry:** media  
**Role:** sole developer

## Problem
The client's team was doing this work by hand and it did not scale. They needed a reliable system they could own.

## What I built
I delivered the project using redis, fastapi, together with a background task queue with workers and retries; a stateful agent graph with branches and human checkpoints.

## Result
The project reached 90% accuracy on a held-out set. The client extended the contract for a second phase.
