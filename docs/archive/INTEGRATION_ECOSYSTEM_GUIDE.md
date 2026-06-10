# Agency OS: Integrated Ecosystem & Critical Resources Guide
## Open-Source Repos, Frontend Stack, GCP Deployment, & Production Essentials

---

## SECTION 1: MOST RELEVANT OPEN-SOURCE REPOS TO INTEGRATE

### **A. AGENTIC ORCHESTRATION & AI FRAMEWORKS**

#### **1. LangChain** (Python)
**Use Case:** Agent orchestration, prompt management, tool calling
- **GitHub:** https://github.com/langchain-ai/langchain
- **Why:** Perfect for CEO orchestrator + sub-agent pattern
- **Integration Point:** Replace manual agent coordination with LangChain agents
```python
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate

# CEO Agent using LangChain
ceo_agent = create_openai_tools_agent(
    llm=ChatOpenAI(model="gpt-4"),
    tools=[analyst_tool, planner_tool, gatekeeper_tool, liaison_tool],
    prompt=ceo_prompt
)

executor = AgentExecutor(agent=ceo_agent, tools=tools, verbose=True)
```
- **Benefit:** Battle-tested agent lifecycle management; reduces custom scaffolding by 60%

#### **2. Anthropic Claude (with Tool Use)**
**Use Case:** More reliable agent execution than GPT-4 for structured tasks
- **GitHub:** https://github.com/anthropics/anthropic-sdk-python
- **Why:** Claude excels at complex decision trees (OPA validation, impact scoring)
- **Integration Point:** Use Claude for Compliance Gatekeeper (most policy-sensitive component)
```python
from anthropic import Anthropic

gatekeeper_client = Anthropic()

# Claude handles complex policy evaluation better than GPT-4
response = gatekeeper_client.messages.create(
    model="claude-3-opus-20240229",
    max_tokens=1024,
    tools=[opa_policy_tools],
    messages=[
        {"role": "user", "content": f"Validate this card against OPA policies: {card}"}
    ]
)
```

#### **3. AutoGPT / AgentGPT Architecture**
**Use Case:** Reference architecture for multi-agent systems
- **GitHub:** https://github.com/Significant-Gravitas/AutoGPT
- **Why:** Shows how to structure agent memory, tool registry, and execution loops
- **Integration Point:** Borrow memory management patterns for sub-agents
- **Benefit:** Proven patterns for handling token limits, context windows

#### **4. LlamaIndex (formerly GPT Index)**
**Use Case:** Semantic search over historical optimization cards & decisions
- **GitHub:** https://github.com/run-llama/llama_index
- **Why:** Enable strategists to query "cards similar to this one" or "past card outcomes"
- **Integration Point:** Index all historical cards; enable natural language search
```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

# Index all historical cards for semantic search
documents = load_optimization_cards_as_documents()
index = VectorStoreIndex.from_documents(documents)

# Query: "Show me budget reallocation cards that worked well"
retriever = index.as_retriever()
results = retriever.retrieve("budget reallocation high-impact cards")
```

---

### **B. MULTI-TENANCY & DATA ISOLATION**

#### **5. Authzed / Zanzibar-Inspired**
**Use Case:** Fine-grained authorization (org → space → card-level permissions)
- **GitHub:** https://github.com/authzed/spicedb
- **Why:** Replaces hardcoded RBAC with declarative policy language
- **Integration Point:** Replace manual role matrix with SpiceDB
```yaml
// SpiceDB schema for Agency OS
definition user {}
definition organization {
  relation member: user
  relation admin: user
}
definition brand {
  relation parent: organization
  relation strategist: user
  permission manage = admin->org.admin | strategist->org.member
}
definition action_card {
  relation parent: brand
  relation creator: user
  permission approve = parent->manage
}
```
- **Benefit:** Prevents path traversal attacks; audit trail built-in

#### **6. Postgres Row-Level Security (RLS)**
**Use Case:** Database-level tenant isolation
- **GitHub:** (Built into PostgreSQL)
- **Why:** Prevent SQL injection from exposing other tenant's data
- **Integration Point:** Add RLS policies to every table
```sql
ALTER TABLE action_cards ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON action_cards
  FOR ALL USING (
    org_id = (current_setting('app.org_id')::uuid) AND
    space_id = (current_setting('app.space_id')::uuid)
  );
```

---

### **C. REAL-TIME COLLABORATION & NOTIFICATIONS**

#### **7. Socket.IO** (Node.js) / **python-socketio** (Python)
**Use Case:** Real-time card approvals, chat collaboration, live notifications
- **GitHub:** https://github.com/socketio/socket.io
- **Why:** Enable approvers to see pending cards appear in real-time
- **Integration Point:** Broadcast card updates to all relevant users
```python
from python_socketio import AsyncServer

sio = AsyncServer(async_mode='aiohttp')

@sio.on('connect')
async def connect(sid, environ):
    user_org = environ['user_org']
    await sio.enter_room(sid, f"org_{user_org}")

# When card is approved, broadcast to all users in org
async def broadcast_card_approval(org_id, card):
    await sio.emit('card_approved', card, room=f"org_{org_id}")
```

#### **8. Temporal Workflows** (Go/Java/Python)
**Use Case:** Durable orchestration for multi-step approval workflows
- **GitHub:** https://github.com/temporalio/temporal
- **Why:** Handle long-running workflows (e.g., "wait for approval, execute after 2 AM")
- **Integration Point:** Replace in-memory state with durable workflows
```python
from temporalio import workflow, activity

@workflow.run
async def optimization_cycle_workflow(org_id: str, space_id: str):
    # This workflow survives server crashes
    telemetry = await analyze_performance(org_id, space_id)
    draft_cards = await plan_optimizations(org_id, space_id, telemetry)
    
    # Wait for human approval (can take hours/days)
    approval_result = await wait_for_approval(draft_cards)
    
    # Execute after approval
    execution_result = await execute_cards(org_id, space_id, approval_result)
    
    return execution_result
```

#### **9. Bull Queue** (Node.js) / **Celery** (Python)
**Use Case:** Async task processing for card generation, validation, execution
- **GitHub:** https://github.com/OptimalBits/bull (Node.js), https://github.com/celery/celery (Python)
- **Why:** Decouple agent execution from API response; handle backpressure
- **Integration Point:** Queue optimization cycles instead of blocking API calls
```python
from celery import Celery

app = Celery('agency_os')

@app.task
def run_optimization_cycle(org_id, space_id):
    # Long-running task; doesn't block API
    analyst = MarketplaceAnalyst()
    planner = OptimizationPlanner()
    
    telemetry = analyst.fetch_metrics(org_id, space_id)
    cards = planner.draft_optimizations(org_id, space_id, telemetry)
    
    # Results stored in DB; UI polls for updates
    return {"cards_generated": len(cards), "total_impact": sum(c.impact_score for c in cards)}
```

#### **10. Slack Bolt** (Python/Node.js)
**Use Case:** Slack-native approvals, notifications, and slash commands
- **GitHub:** https://github.com/slackapi/bolt-python
- **Why:** Let approvers approve cards without leaving Slack
- **Integration Point:** Send cards to Slack; handle approval callbacks
```python
from slack_bolt import App

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

@app.action("approve_card")
def handle_approve(ack, body, say):
    ack()
    card_id = body["actions"][0]["value"]
    
    # Approve in Agency OS
    approve_card_in_db(card_id)
    
    say(f"✅ Card {card_id} approved!")
```

---

### **D. OBSERVABILITY & MONITORING**

#### **11. OpenTelemetry** (Vendor-agnostic)
**Use Case:** Distributed tracing, metrics, logs across all agents and services
- **GitHub:** https://github.com/open-telemetry/opentelemetry-python
- **Why:** Trace card execution from Analyst → Planner → Gatekeeper → Liaison
- **Integration Point:** Instrument every function
```python
from opentelemetry import trace, metrics

tracer = trace.get_tracer(__name__)

def draft_optimizations(org_id, space_id):
    with tracer.start_as_current_span("draft_optimizations") as span:
        span.set_attribute("org_id", org_id)
        span.set_attribute("space_id", space_id)
        
        # ... optimization logic
        
        span.set_attribute("cards_generated", len(cards))
```

#### **12. Prometheus + Grafana**
**Use Case:** Metrics visualization and alerting
- **GitHub:** https://github.com/prometheus/prometheus, https://github.com/grafana/grafana
- **Why:** Monitor card throughput, approval rates, error rates
- **Integration Point:** Expose metrics in Prometheus format
```python
from prometheus_client import Counter, Histogram

cards_generated = Counter('cards_generated_total', 'Total cards generated', ['org_id', 'card_type'])
approval_latency = Histogram('approval_latency_seconds', 'Time to approve card')

@app.route('/api/approve', methods=['POST'])
def approve():
    start = time.time()
    # ... approval logic
    approval_latency.observe(time.time() - start)
```

#### **13. Sentry** (Error tracking)
**Use Case:** Real-time error monitoring and alerting
- **GitHub:** https://github.com/getsentry/sentry
- **Why:** Alert ops team immediately if card validation fails
- **Integration Point:** Wrap all agent functions with Sentry
```python
import sentry_sdk

sentry_sdk.init("https://examplePublicKey@o0.ingest.sentry.io/0")

def validate_card(card):
    try:
        # validation logic
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
```

---

### **E. DATA & ANALYTICS**

#### **14. Kafka / Apache Pulsar**
**Use Case:** Event streaming for card approvals, rejections, executions
- **GitHub:** https://github.com/apache/kafka, https://github.com/apache/pulsar
- **Why:** Enable Event Sourcing; allow downstream systems (BI, analytics) to consume events
- **Integration Point:** Stream all card state changes to Kafka topics
```python
from kafka import KafkaProducer

producer = KafkaProducer(bootstrap_servers=['localhost:9092'])

def approve_card(card_id):
    card = db.get_card(card_id)
    card.status = "APPROVED"
    db.save(card)
    
    # Emit event for Event Sourcing
    producer.send('cards-approved', {
        'card_id': card_id,
        'impact_score': card.impact_score,
        'timestamp': now()
    })
```

#### **15. dbt (Data Build Tool)**
**Use Case:** SQL transformations for reporting and analytics
- **GitHub:** https://github.com/dbt-labs/dbt-core
- **Why:** Build data warehouse models for executive dashboards
- **Integration Point:** Transform raw card execution data into KPIs
```sql
-- dbt model: card_performance.sql
select
  card_id,
  recommendation_type,
  impact_score,
  actual_revenue_impact,
  approval_latency,
  date(created_at) as approval_date
from raw_action_cards
where status = 'APPROVED'
```

---

## SECTION 2: FRONTEND UX/UI - CLEAR TECHNOLOGY PATH

### **A. RECOMMENDED TECH STACK**

#### **Framework: React 19 + TypeScript**
**Why:**
- Component-based architecture scales to 100s of screens
- TypeScript catches bugs before production
- Massive ecosystem (next choice covers routing)

#### **Routing: Next.js 15** (Server Components + App Router)
**Why:**
- Built-in SEO, SSR, ISR for dashboards
- API routes eliminate need for separate backend for simple operations
- Image optimization, code splitting out of box

#### **UI Components: Shadcn/ui** (Headless Radix + Tailwind)
**Why:**
- Copy-paste components; no vendor lock-in
- Accessible by default (WCAG 2.1)
- Customizable with Tailwind

#### **State Management: TanStack Query v5** (formerly React Query)
**Why:**
- Auto-caching of approval queues, dashboards
- Real-time synchronization with backend
- Replaces Redux for 90% of use cases

#### **Tables/Data Display: TanStack Table v8**
**Why:**
- Headless table library; works with any UI framework
- Client-side pagination, sorting, filtering
- Perfect for displaying 10K+ cards with 60fps performance

---

### **B. COMPONENT LIBRARY STRUCTURE**

```
src/components/
├── dashboard/
│   ├── ExecutiveSummary.tsx (CEO dashboard)
│   ├── ClientPerformance.tsx (CSM dashboard)
│   ├── StrategistAnalytics.tsx (Strategist dashboard)
│   └── ComplianceAudit.tsx (Compliance dashboard)
├── approval/
│   ├── ApprovalCard.tsx (individual card display)
│   ├── ApprovalQueue.tsx (list of pending cards)
│   ├── BatchApprovalModal.tsx (bulk approve)
│   └── ParameterAdjustment.tsx (tweak card parameters)
├── integrations/
│   ├── GoogleAdsStatus.tsx (integration health)
│   ├── FacebookAdsStatus.tsx
│   └── IntegrationMonitor.tsx
├── collaboration/
│   ├── CardComments.tsx (threaded discussion)
│   ├── MentionInput.tsx (@mention people)
│   └── NotificationCenter.tsx
└── common/
    ├── Layout.tsx
    ├── Navbar.tsx
    ├── Sidebar.tsx (role-based navigation)
    └── AccessControl.tsx (guards for RBAC)
```

---

### **C. DESIGN SYSTEM & ACCESSIBILITY**

#### **Design Tokens (Tailwind Config)**
```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        'status-approved': '#10B981',
        'status-rejected': '#EF4444',
        'status-pending': '#F59E0B',
        'tier-0': '#DC2626', // Lockout (red)
        'tier-1': '#F59E0B', // Semi (yellow)
        'tier-2': '#10B981', // Full (green)
      },
      fontSize: {
        'body-sm': ['14px', { lineHeight: '1.5' }],
        'body-md': ['16px', { lineHeight: '1.6' }],
        'heading-xl': ['32px', { lineHeight: '1.2' }],
      }
    }
  }
}
```

#### **Accessibility Features (Required)**
- ✅ ARIA labels on all interactive elements
- ✅ Keyboard navigation (Tab, Enter, Escape)
- ✅ Color-blind friendly palette
- ✅ Screen reader testing (Jaws, NVDA)
- ✅ Form validation with clear error messages

---

### **D. KEY UI SCREENS (WITH WIREFRAME LOGIC)**

#### **1. Executive Dashboard**
```
┌─────────────────────────────────────────────────────┐
│ Agency OS Control Panel           [Logout] [Settings]│
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ Portfolio Health                                │ │
│ │ • Total ARR: $2.1M (↑12% vs. last month)       │ │
│ │ • Brands in Tier 2: 67% (↑8%)                  │ │
│ │ • Cards Approved This Month: 4,231             │ │
│ │ • Avg Approval Latency: 4.2 minutes            │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Top Performing Strategists         [Leaderboard]│ │
│ │ 1. Jane (128 approvals, $890K impact)          │ │
│ │ 2. Bob (96 approvals, $720K impact)            │ │
│ │ 3. Sarah (84 approvals, $605K impact)          │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ At-Risk Brands              [See All] [Dismiss]   │ │
│ │ ⚠️ Brand_X: Tier 2 → Tier 1 predicted in 3 days │ │
│ │ ⚠️ Brand_Y: GMC mismatches increasing 15% WoW    │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

#### **2. Approval Queue (CSM/Strategist View)**
```
┌─────────────────────────────────────────────────────┐
│ Pending Approvals (14)    [Filter] [Bulk Approve]   │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ ☐ BID_ADJUSTMENT | Brand_X Campaign_5          │ │
│ │   Impact Score: 8.5/10  | Estimated +$12K/mo   │ │
│ │   Current Bid: $2.50 → Proposed: $5.00 (2x)    │ │
│ │   ┌─────────────────────────────────────────┐  │ │
│ │   │ ✓ Schema validation passed              │  │ │
│ │   │ ✓ OPA policy check passed               │  │ │
│ │   │ ✓ Budget within tier limits             │  │ │
│ │   └─────────────────────────────────────────┘  │ │
│ │   [📝 Edit Amount] [📞 Escalate] [✅ Approve]  │ │
│ │   [❌ Reject] [⏱️ Snooze until 2 AM]            │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ☐ BUDGET_REALLOCATION | Brand_Y                │ │
│ │   Impact Score: 6.2/10 | Estimated +$8.5K/mo  │ │
│ │   Move $1000 from Campaign_2 → Campaign_8      │ │
│ │   [Similar cards: 47 historical] [Show Results] │ │
│ │   [✅ Approve] [❌ Reject] [💬 Ask Strategist]  │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

#### **3. Campaign Analytics (Strategist Deep-Dive)**
```
┌─────────────────────────────────────────────────────┐
│ Campaign Analytics: Brand_X                         │
├─────────────────────────────────────────────────────┤
│ Campaign_5 Performance (Last 30 Days)               │
│                                                      │
│ Spend: $45,000    Conversions: 1,800    ROAS: 2.8 │
│ COAS: $25.00      CPC: $8.50            CTR: 3.2% │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Daily ROAS Trend           [Download Chart]     │ │
│ │ 4.0│      ╱╲                                    │ │
│ │ 3.5│     ╱  ╲    ╱╲                             │ │
│ │ 3.0│    ╱    ╲  ╱  ╲                            │ │
│ │ 2.5│───────────────────                         │ │
│ │ 2.0└─────────────────────────                   │ │
│ │    Day 1    Day 10    Day 20    Day 30          │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ Performance vs. Peers (Retail vertical)             │
│ Your COAS: $25.00                                   │
│ Median:    $28.50 (↑14% better than avg)            │
│ Top 10%:   $18.00 (opportunity: $7 gap)             │ │
│                                                      │
│ Recommended Actions:                                │
│ 1. ↑ Bid by $3 (peer data suggests ROI positive)   │
│ 2. Expand lookalike audience (2% audience overlap)  │
│ 3. Enable enhanced conversions (CAPI match: 68%)    │
│                                                      │
│ [📊 Confidence: 87%] [Generate Optimization Cards] │
└─────────────────────────────────────────────────────┘
```

---

### **E. RECOMMENDED LIBRARIES (COMPLETE STACK)**

```json
{
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "typescript": "^5.3.0",
    "@tanstack/react-query": "^5.0.0",
    "@tanstack/react-table": "^8.0.0",
    "@hookform/resolvers": "^3.3.0",
    "react-hook-form": "^7.48.0",
    "zod": "^3.22.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-popover": "^1.0.0",
    "@radix-ui/react-tabs": "^1.0.0",
    "tailwindcss": "^3.3.0",
    "lucide-react": "^0.292.0",
    "recharts": "^2.10.0",
    "clsx": "^2.0.0",
    "date-fns": "^2.30.0",
    "framer-motion": "^10.16.0",
    "socket.io-client": "^4.7.0",
    "@slack/web-api": "^6.9.0",
    "axios": "^1.6.0",
    "sentry/nextjs": "^7.78.0"
  },
  "devDependencies": {
    "@testing-library/react": "^14.0.0",
    "@testing-library/jest-dom": "^6.1.0",
    "vitest": "^0.34.0",
    "playwright": "^1.40.0",
    "prettier": "^3.0.0",
    "eslint": "^8.52.0"
  }
}
```

---

## SECTION 3: GCP CONTROL PANEL - BUILD, HOST, TRANSFER & MANAGE

### **A. RECOMMENDED GCP ARCHITECTURE**

#### **High-Level Infrastructure**
```
┌─────────────────────────────────────────────────────────┐
│                   Cloud Load Balancer                    │
│              (SSL termination, routing)                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │     Google Kubernetes Engine (GKE)              │   │
│  │     (Multi-zone, autoscaling 5-50 nodes)        │   │
│  │                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐            │   │
│  │  │ API Pods     │  │ Agent Pods    │            │   │
│  │  │ (10 replicas)│  │ (20 replicas) │            │   │
│  │  └──────────────┘  └──────────────┘            │   │
│  │                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐            │   │
│  │  │ Worker Pods  │  │ Scheduler Pod │            │   │
│  │  │ (20 replicas)│  │ (3 replicas)  │            │   │
│  │  └──────────────┘  └──────────────┘            │   │
│  └─────────────────────────────────────────────────┘   │
│                          ↓                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │    Cloud SQL (PostgreSQL)                       │   │
│  │    • Hot standby (HA replicas)                  │   │
│  │    • Automated backups (30-day retention)       │   │
│  │    • Point-in-time recovery                     │   │
│  └─────────────────────────────────────────────────┘   │
│                          ↓                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │    Cloud Storage (GCS)                          │  │
│  │    • Audit logs (multi-region replication)      │  │
│  │    • Card execution history                     │  │
│  │    • Customer backups                           │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │  Cloud Tasks │  │ Cloud Pub/Sub │                  │
│  │  (scheduled  │  │ (event stream)│                  │
│  │   jobs)      │  │               │                  │
│  └──────────────┘  └──────────────┘                  │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │Cloud Logging │  │Cloud Monitoring                  │
│  │(ElK-like)    │  │(Prometheus-like)│                │
│  └──────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

---

### **B. TERRAFORM INFRASTRUCTURE AS CODE (IaC)**

#### **Directory Structure**
```
infrastructure/
├── terraform/
│   ├── main.tf              # GKE cluster definition
│   ├── database.tf          # Cloud SQL PostgreSQL
│   ├── storage.tf           # Cloud Storage buckets
│   ├── networking.tf        # VPC, subnets, firewall
│   ├── monitoring.tf        # Cloud Monitoring, Logging
│   ├── secrets.tf           # Secret Manager for API keys
│   ├── variables.tf         # Input variables
│   ├── outputs.tf           # Exported values
│   └── terraform.tfvars    # Environment-specific values
├── helm/
│   ├── agency-os/
│   │   ├── Chart.yaml
│   │   ├── values-dev.yaml
│   │   ├── values-staging.yaml
│   │   ├── values-prod.yaml
│   │   └── templates/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       ├── configmap.yaml
│   │       └── hpa.yaml (autoscaling)
│   └── dependencies/
│       ├── postgres-operator/
│       ├── redis-operator/
│       └── prometheus-operator/
└── scripts/
    ├── setup.sh             # First-time setup
    ├── deploy.sh            # CI/CD deployment
    └── backup.sh            # Backup procedures
```

#### **Sample Terraform: GKE Cluster**
```hcl
# infrastructure/terraform/main.tf

resource "google_container_cluster" "agency_os" {
  name     = "agency-os-${var.environment}"
  location = var.gcp_region
  
  # Node pool configuration
  node_pool {
    name       = "default-pool"
    node_count = var.initial_node_count
    
    autoscaling {
      min_node_count = var.min_nodes
      max_node_count = var.max_nodes
    }
    
    node_config {
      machine_type = "n2-standard-4"
      disk_size_gb = 100
      
      oauth_scopes = [
        "https://www.googleapis.com/auth/cloud-platform"
      ]
      
      labels = {
        environment = var.environment
        managed_by  = "terraform"
      }
    }
  }
  
  # Enable required APIs
  addons_config {
    http_load_balancing_config {
      disabled = false
    }
    horizontal_pod_autoscaling {
      disabled = false
    }
  }
  
  # Network configuration
  network    = google_compute_network.vpc.name
  subnetwork = google_compute_subnetwork.subnet.name
  
  # Security
  master_auth {
    client_certificate_config {
      issue_client_certificate = false
    }
  }
}

# Load Balancer
resource "google_compute_backend_service" "agency_os" {
  name            = "agency-os-backend"
  protocol        = "HTTPS"
  health_checks   = [google_compute_health_check.agency_os.id]
  session_affinity = "CLIENT_IP"
  
  backend {
    group           = google_container_node_pool.agency_os.instance_group_urls[0]
    balancing_mode  = "RATE"
    max_rate_per_endpoint = 1000
  }
}
```

#### **Sample Helm Values (Production)**
```yaml
# infrastructure/helm/agency-os/values-prod.yaml

replicaCount: 10  # High availability

image:
  repository: gcr.io/agency-os-prod/api
  tag: "1.2.3"
  pullPolicy: IfNotPresent

resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "4Gi"
    cpu: "2000m"

autoscaling:
  enabled: true
  minReplicas: 10
  maxReplicas: 50
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

postgresql:
  enabled: true
  auth:
    database: agency_os
    username: app_user
    existingSecret: pg-credentials
  primary:
    resources:
      requests:
        memory: "8Gi"
        cpu: "4000m"
    persistence:
      size: 500Gi
      storageClassName: "fast-ssd"

redis:
  enabled: true
  auth:
    existingSecret: redis-credentials
  master:
    resources:
      requests:
        memory: "4Gi"
        cpu: "2000m"

ingress:
  enabled: true
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: agency-os.com
      paths:
        - path: /
          pathType: Prefix

monitoring:
  enabled: true
  prometheus:
    enabled: true
  grafana:
    enabled: true
    adminPassword: ${GRAFANA_ADMIN_PASSWORD}  # From Secret Manager
```

---

### **C. DEPLOYMENT AUTOMATION (CI/CD)**

#### **GitHub Actions Workflow**
```yaml
# .github/workflows/deploy-prod.yml

name: Deploy to Production

on:
  push:
    branches:
      - main

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          npm install
          npm run test
          npm run lint

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker image
        run: |
          docker build -t gcr.io/agency-os-prod/api:${{ github.sha }} .
      - name: Push to GCR
        run: |
          gcloud auth configure-docker gcr.io
          docker push gcr.io/agency-os-prod/api:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to GKE
        run: |
          gcloud container clusters get-credentials agency-os-prod --zone us-central1-a
          
          # Helm upgrade with blue-green deployment
          helm upgrade agency-os ./infrastructure/helm/agency-os \
            --values ./infrastructure/helm/agency-os/values-prod.yaml \
            --set image.tag=${{ github.sha }} \
            --namespace production \
            --wait \
            --timeout 10m
          
          # Health check
          kubectl rollout status deployment/agency-os -n production
      
      - name: Run smoke tests
        run: |
          kubectl port-forward -n production svc/agency-os 8080:80 &
          sleep 5
          curl -f http://localhost:8080/health || exit 1
```

---

### **D. DATABASE MIGRATION & DATA TRANSFER**

#### **Backup & Disaster Recovery**
```bash
#!/bin/bash
# infrastructure/scripts/backup.sh

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_BUCKET="gs://agency-os-backups"

# 1. Full database export
gcloud sql export sql agency-os-prod \
  ${BACKUP_BUCKET}/postgres_${TIMESTAMP}.sql

# 2. Verify backup
gsutil ls -l ${BACKUP_BUCKET}/postgres_${TIMESTAMP}.sql

# 3. Test restore (in staging)
gcloud sql import sql agency-os-staging \
  ${BACKUP_BUCKET}/postgres_${TIMESTAMP}.sql

echo "✅ Backup completed: ${BACKUP_BUCKET}/postgres_${TIMESTAMP}.sql"
```

#### **Database Migration Path**
```sql
-- Migration: 001_initial_schema.sql

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    data_residency VARCHAR(50) DEFAULT 'us-central1',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_tenant_name UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS brands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    gtm_present BOOLEAN DEFAULT FALSE,
    pixel_present BOOLEAN DEFAULT FALSE,
    capi_dedup_rate DECIMAL(3,2),
    autonomy_tier INTEGER DEFAULT 0,
    trust_score DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_brand_per_tenant UNIQUE(tenant_id, name)
);

-- Row-level security
ALTER TABLE brands ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON brands
  FOR ALL USING (
    tenant_id = (current_setting('app.tenant_id')::uuid)
  );

CREATE INDEX idx_brands_tenant_id ON brands(tenant_id);
CREATE INDEX idx_brands_autonomy_tier ON brands(autonomy_tier);
```

---

### **E. COST MANAGEMENT & OPTIMIZATION**

#### **Cost Monitoring Dashboard**
```
┌─────────────────────────────────────────────┐
│   Agency OS - GCP Cost Dashboard             │
├─────────────────────────────────────────────┤
│                                             │
│ Current Month Spend: $42,500                │
│ Projected Month Total: $51,000              │
│ Budget: $60,000 (85% utilized) ⚠️            │
│                                             │
│ Cost by Service:                            │
│ • GKE Compute:      $28,000 (54%)           │
│ • Cloud SQL:        $12,000 (23%)           │
│ • Cloud Storage:    $4,200  (8%)            │
│ • Networking:       $3,100  (6%)            │
│ • Cloud Logging:    $2,800  (5%)            │
│ • Other:            $2,900  (4%)            │
│                                             │
│ Optimization Opportunities:                 │
│ ✓ Reduce compute by 20% with spot VMs      │
│ ✓ Use Reserved Instances for baseline      │
│ ✓ Enable GCS lifecycle rules (save $1.2K)  │
│                                             │
│ Potential Savings: $8,200/month (16%)      │
└─────────────────────────────────────────────┘
```

#### **Cost Optimization Script**
```python
# infrastructure/scripts/optimize_costs.py

import google.cloud.billing_v1

def enable_spot_vms():
    """Use Spot VMs for non-critical workloads (70% cheaper)"""
    # Configure worker nodes as spot instances
    config = {
        "node_pool": "worker-pool",
        "machine_type": "n2-standard-4",
        "preemptible": True,
        "auto_repair": True,
        "auto_upgrade": True
    }
    # Save ~$8K/month

def use_reserved_instances():
    """Purchase 3-year commitment for baseline load"""
    # Reduce compute cost by 40% on committed capacity
    # Save ~$12K/month

def cleanup_unused_resources():
    """Remove orphaned disks, IPs, snapshots"""
    compute = google.cloud.compute_v1.DisksClient()
    for disk in compute.list(project="agency-os-prod"):
        if disk.users is None or len(disk.users) == 0:
            compute.delete(disk.name)
            print(f"Deleted orphaned disk: {disk.name}")
    # Save ~$2K/month

if __name__ == "__main__":
    print("💾 Optimization Recommendations:")
    print("1. Enable Spot VMs: Save $8,200/month")
    print("2. Use Reserved Instances: Save $12,500/month")
    print("3. Clean up unused resources: Save $2,100/month")
    print("═" * 50)
    print("Total Potential Savings: $22,800/month (45% reduction)")
```

---

## SECTION 4: CRITICAL RESOURCES TO SHARE / REFERENCE

### **A. MUST-READ DOCUMENTATION**

#### **1. Architecture & Design Patterns**
| Resource | Link | Why Critical |
|----------|------|---|
| **CQRS Pattern** | https://martinfowler.com/bliki/CQRS.html | Separate read/write models for dashboards |
| **Event Sourcing** | https://martinfowler.com/eaaDev/EventSourcing.html | Immutable card execution history |
| **Saga Pattern** | https://microservices.io/patterns/data/saga.html | Distributed transactions across agents |
| **Multi-tenant SaaS Architecture** | https://stripe.com/blog/multi-tenant-saas | Path isolation + data security |
| **API Design Best Practices** | https://restfulapi.net/ | Design OpenAPI 3.0 spec properly |

#### **2. Security & Compliance**
| Resource | Link | Why Critical |
|----------|------|---|
| **OWASP Top 10** | https://owasp.org/www-project-top-ten/ | Common vulnerabilities to prevent |
| **NIST Cybersecurity Framework** | https://www.nist.gov/cyberframework | Governance structure for security |
| **GDPR Compliance Checklist** | https://gdpr-info.eu/ | EU data protection requirements |
| **SOC 2 Compliance** | https://www.aicpa.org/soc2 | Audit-ready controls |

#### **3. Operations & DevOps**
| Resource | Link | Why Critical |
|----------|------|---|
| **Kubernetes Best Practices** | https://kubernetes.io/docs/concepts/configuration/overview/ | Production-grade orchestration |
| **The 12-Factor App** | https://12factor.net/ | Build scalable SaaS applications |
| **SRE Book** | https://sre.google/books/ | Operations for reliability |

---

### **B. CRITICAL CODE TEMPLATES TO REUSE**

#### **1. Multi-Tenant Request Handler**
```python
# Ensure every request validates tenant context
from functools import wraps
from flask import request, abort

def require_tenant_context(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        org_id = request.headers.get('X-Org-ID')
        space_id = request.headers.get('X-Space-ID')
        
        if not org_id or not space_id:
            abort(400, "Missing tenant context headers")
        
        # Verify user has access to this org/space
        current_user = get_current_user()
        if not current_user.has_access(org_id, space_id):
            abort(403, "Access denied")
        
        # Set context for DB queries (RLS)
        db.session.execute(
            f"SET app.org_id = '{org_id}'; SET app.space_id = '{space_id}';"
        )
        
        return f(*args, org_id=org_id, space_id=space_id, **kwargs)
    
    return decorated_function

@app.route('/api/cards')
@require_tenant_context
def get_cards(org_id, space_id):
    # All queries are automatically filtered by RLS
    cards = db.query(ActionCard).all()
    return jsonify(cards)
```

#### **2. Error Handling & Observability**
```python
# Structured error responses with trace ID
import uuid
import logging

logger = logging.getLogger(__name__)

@app.errorhandler(Exception)
def handle_error(error):
    trace_id = str(uuid.uuid4())
    
    # Log with context
    logger.error(f"Trace ID: {trace_id}", exc_info=True)
    
    # Send to Sentry
    sentry_sdk.capture_exception(error)
    
    # Return user-friendly response
    return {
        "error": str(error),
        "trace_id": trace_id,
        "status": "error"
    }, 500
```

#### **3. Feature Flags**
```python
# Use feature flags for gradual rollouts
from flagsmith import Flagsmith

flagsmith = Flagsmith(api_key="your-api-key")

@app.route('/api/optimize')
def optimize(org_id):
    # Check if org is in A/B test
    if flagsmith.is_feature_enabled("ml_planner_v2", org_id):
        planner = MLPlanner()  # New implementation
    else:
        planner = HeuristicPlanner()  # Old implementation
    
    return planner.draft_optimizations(org_id)
```

---

### **C. EXTERNAL SERVICES TO INTEGRATE**

#### **1. Monitoring & Observability**
```python
# Pre-configured integrations

# Sentry (Error tracking)
import sentry_sdk
sentry_sdk.init("https://examplePublicKey@o0.ingest.sentry.io/0")

# Datadog (Metrics + APM)
from datadog import api
api.api_key = os.environ['DATADOG_API_KEY']

# New Relic (Performance monitoring)
import newrelic.agent
newrelic.agent.initialize('newrelic.ini')

# Honeycomb (Observability)
from honeycomb import new_client
client = new_client(apikey=os.environ['HONEYCOMB_API_KEY'])
```

#### **2. Communication**
```python
# Pre-configured integrations

# Slack
from slack_bolt import App
app = App(token=os.environ['SLACK_BOT_TOKEN'])

# Email (SendGrid)
from sendgrid import SendGridAPIClient
sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))

# SMS (Twilio)
from twilio.rest import Client
client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
```

#### **3. Payment & Billing**
```python
# Pre-configured integrations

# Stripe (Payment processing)
import stripe
stripe.api_key = os.environ['STRIPE_SECRET_KEY']

# Chargebee (Subscription management)
from chargebee import chargebee
chargebee.configure(os.environ['CHARGEBEE_API_KEY'], "your-domain.chargebee.com")
```

---

### **D. DEPLOYMENT CHECKLIST**

Before going to production, verify:

#### **Security**
- [ ] All secrets (API keys, DB passwords) stored in Secret Manager, not code
- [ ] Database encryption at rest enabled
- [ ] TLS/SSL certificates for all endpoints
- [ ] SQL injection prevention (parameterized queries)
- [ ] CORS properly configured (no overly permissive origins)
- [ ] Rate limiting enabled on all APIs
- [ ] DDoS protection (Google Cloud Armor)

#### **Performance**
- [ ] Database queries optimized (indexes created)
- [ ] Caching layers in place (Redis)
- [ ] CDN enabled for static assets
- [ ] Load testing completed (target 10,000 req/sec)
- [ ] P99 latency < 500ms under peak load

#### **Reliability**
- [ ] Multi-region failover tested
- [ ] Backup & restore procedure verified
- [ ] Incident response runbook documented
- [ ] On-call rotation established
- [ ] Monitoring & alerting configured

#### **Compliance**
- [ ] GDPR compliance audit passed
- [ ] SOC 2 controls documented
- [ ] Data residency requirements met
- [ ] Audit logs immutable and complete
- [ ] Privacy policy updated

#### **Operational**
- [ ] Documentation complete (API docs, runbooks)
- [ ] Observability dashboards created
- [ ] Alerting thresholds tuned (not too sensitive)
- [ ] Log retention policies configured
- [ ] Cost monitoring enabled

---

## SECTION 5: REPO INTEGRATION ROADMAP

### **Phase 1: Foundation (Weeks 1-4)**
- [ ] Set up GCP project, Terraform infrastructure
- [ ] Integrate LangChain for agent orchestration
- [ ] Implement multi-tenant isolation (path-based + RLS)
- [ ] Set up Next.js frontend skeleton

### **Phase 2: Core MVP (Weeks 5-12)**
- [ ] Build Approval Queue UI (Shadcn + TanStack Table)
- [ ] Implement CEO + Sub-agent orchestration
- [ ] OneMCP router for integrations
- [ ] Basic dashboards (Executive, Strategist, CSM)

### **Phase 3: Scale & Intelligence (Weeks 13-20)**
- [ ] Add Kafka event streaming
- [ ] Implement Temporal workflows
- [ ] Real-time collaboration (Socket.IO)
- [ ] Slack/Teams integration (Slack Bolt)

### **Phase 4: Production Hardening (Weeks 21-28)**
- [ ] Observability stack (OpenTelemetry, Prometheus, Grafana)
- [ ] Disaster recovery & backup procedures
- [ ] Cost optimization & monitoring
- [ ] Security audit (OWASP, SOC 2)

---

## CONCLUSION: INTEGRATION PRIORITY

**HIGH PRIORITY (Month 1)**
1. Next.js + Shadcn/ui (frontend foundation)
2. LangChain (agent orchestration)
3. PostgreSQL + RLS (multi-tenancy)
4. GKE + Terraform (infrastructure)

**MEDIUM PRIORITY (Month 2-3)**
5. Socket.IO (real-time updates)
6. Slack Bolt (notifications)
7. OpenTelemetry (observability)
8. Kafka (event streaming)

**NICE-TO-HAVE (Month 4+)**
9. Temporal (durable workflows)
10. LlamaIndex (semantic search)
11. Anthropic Claude (specialized agent)
12. dbt (data warehouse)

