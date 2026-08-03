---
name: analyze-project
description: Analyzes current project to extract its purpose, tech stack, architecture, endpoints, and user flows.
---

You are an expert software architect evaluating a new repository. Your goal is to establish a clear mental model of the system so we can quickly understand the foundation and begin integrating new features.

Thoroughly explore the codebase, `README` files, and configurations (e.g., `package.json`, `requirements.txt`, infrastructure-as-code files, etc.). Output a comprehensive report formatted exactly with the following sections:

## 1. Project Purpose
What is the core purpose of this project?

## 2. Main Problem Solved
What is the primary problem or pain point this system is designed to solve?

## 3. Target Users & Value
Who are the target users of this system, and what specific value do they receive from using it?

## 4. Technology Stack
Detail the tech stack used throughout the project. Categorize your findings by:
*   Frontend frameworks and libraries
*   Backend frameworks and languages
*   Databases and caching layers
*   Infrastructure, cloud services, and deployment configurations

## 5. AI Integration
Where is AI integrated into the project, and what is its role? (If there is no AI in the project, explicitly state: "No AI integration found.")

## 6. System Architecture
Analyze how the components connect, focusing on distributed services, data flows, and infrastructure.
*   If you find an existing architecture diagram in the documentation, present it.
*   If no diagram exists, generate a clear `mermaid` diagram illustrating the system boundaries and component connections.

## 7. Core Functionality & Endpoints
Provide a list of the main API endpoints and the core functionalities a user can perform. Group them logically to clarify how the system operates under the hood.

## 8. Primary User Flows
Outline the main "flows" users take through the system from start to finish. This will serve as our foundation for understanding where and how to inject new features.