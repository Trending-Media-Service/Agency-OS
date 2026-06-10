-- Agency OS Core Database Schema (Supabase/PostgreSQL)
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =========================================================================
-- 1. TABLES DEFINITIONS
-- =========================================================================

-- Tenants (Client Brands) Table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    base_currency VARCHAR(3) DEFAULT 'USD' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Users Table with Role Mapping
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL, -- e.g., 'AGENCY_OWNER', 'CLIENT_DBA', 'MEDIA_BUYER'
    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL, -- NULL for multi-tenant Agency users
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Product-to-Ad SKU Cross-Reference Table
CREATE TABLE product_ad_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    gmc_offer_id VARCHAR(100) NOT NULL,
    google_campaign_id VARCHAR(100),
    google_ad_group_id VARCHAR(100),
    inventory_status VARCHAR(50) DEFAULT 'IN_STOCK' NOT NULL,
    current_stock_count INT DEFAULT 0 NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, sku)
);

-- Dynamic Action Cards Queue Table
CREATE TABLE action_cards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trigger_event VARCHAR(100) NOT NULL, -- e.g., 'SKU_STOCKOUT', 'PIXEL_MISFIRE'
    blocker_category VARCHAR(50) NOT NULL, -- e.g., 'CATALOG_VISIBILITY', 'TRACKING'
    autonomy_tier INT NOT NULL CHECK (autonomy_tier IN (0, 1, 2)),
    status VARCHAR(50) DEFAULT 'PENDING_REVIEW' NOT NULL, -- 'PENDING_REVIEW', 'APPROVED', 'EXECUTED', 'REJECTED'
    confidence_score NUMERIC(5, 4) NOT NULL,
    proposed_actions JSONB NOT NULL, -- Detailed payload of mutations & API calls
    reversal_mutations JSONB, -- Payload to rollback changes
    rationale TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Immutable Trust Ledger & Action Audit Log
CREATE TABLE trust_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    action_card_id UUID REFERENCES action_cards(id) ON DELETE SET NULL,
    executor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR(100) NOT NULL,
    tier_executed INT NOT NULL,
    execution_status VARCHAR(50) NOT NULL, -- 'SUCCESS', 'FAILED', 'REVERSED'
    reversal_payload JSONB,
    feedback_score INT CHECK (feedback_score BETWEEN -1 AND 1), -- Client sentiment feedback
    payload_snapshot JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Privacy-Preserving Cross-Tenant Benchmarks Table
CREATE TABLE benchmarks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vertical VARCHAR(100) NOT NULL,
    region VARCHAR(50) NOT NULL,
    metric_date DATE NOT NULL,
    avg_cpc NUMERIC(10, 4),
    avg_cpm NUMERIC(10, 4),
    avg_ctr NUMERIC(5, 4),
    active_tenants_count INT NOT NULL CHECK (active_tenants_count >= 5), -- Hard privacy gate
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vertical, region, metric_date)
);

-- Secure Credentials Vault Table
CREATE TABLE credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    credential_type VARCHAR(100) NOT NULL, -- e.g., 'SHOPIFY_API_KEY', 'GOOGLE_OAUTH_TOKEN', 'SSH_PRIVATE_KEY'
    encrypted_payload BYTEA NOT NULL, -- Encrypted credential data
    key_id VARCHAR(100) NOT NULL, -- Reference to KMS key
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, credential_type)
);

-- =========================================================================
-- 2. INDEXES
-- =========================================================================
CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_product_ad_links_tenant_sku ON product_ad_links(tenant_id, sku);
CREATE INDEX idx_action_cards_tenant_status ON action_cards(tenant_id, status);
CREATE INDEX idx_trust_ledger_tenant ON trust_ledger(tenant_id);
CREATE INDEX idx_benchmarks_lookup ON benchmarks(vertical, region, metric_date);
CREATE INDEX idx_credentials_tenant ON credentials(tenant_id);

-- =========================================================================
-- 3. ROW LEVEL SECURITY (RLS) SETUP
-- =========================================================================

-- Enable RLS on all tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_ad_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE trust_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE benchmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE credentials ENABLE ROW LEVEL SECURITY;

-- Context Helper Functions
CREATE OR REPLACE FUNCTION get_current_tenant_id() RETURNS UUID AS $$
    -- Retrieves the current active tenant UUID passed by the server middleware
    SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::UUID;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION get_current_user_role() RETURNS VARCHAR AS $$
    -- Retrieves the role of the authenticated active user session
    SELECT NULLIF(current_setting('app.current_user_role', true), '')::VARCHAR;
$$ LANGUAGE sql STABLE;

-- RLS Policies

-- A. Tenants Policies
CREATE POLICY tenant_isolation_policy ON tenants
    FOR SELECT
    USING (
        id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER')
    );

-- B. Users Policies
CREATE POLICY tenant_users_policy ON users
    FOR ALL
    USING (
        tenant_id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER')
    );

-- C. Product Ad Links Policies
CREATE POLICY tenant_links_policy ON product_ad_links
    FOR ALL
    USING (
        tenant_id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER', 'AGENCY_MEDIA_BUYER')
    );

-- D. Action Cards Policies (Isolation & Mutation Rights)
CREATE POLICY tenant_action_cards_policy ON action_cards
    FOR ALL
    USING (
        tenant_id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER', 'AGENCY_MEDIA_BUYER', 'AGENCY_ANALYTICS_ENGINEER')
    )
    WITH CHECK (
        -- Clients can update statuses of their own actions cards (Approvals/Rejections)
        (tenant_id = get_current_tenant_id() AND get_current_user_role() IN ('CLIENT_EXECUTIVE', 'CLIENT_DBA', 'CLIENT_SALES_OPS'))
        OR
        -- Agency Admins and designated buyers can draft, validate or update cards
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER', 'AGENCY_ANALYTICS_ENGINEER', 'AGENCY_MEDIA_BUYER')
    );

-- E. Trust Ledger Policies (Read-Only for Tenant/Agency Admins)
CREATE POLICY tenant_trust_ledger_policy ON trust_ledger
    FOR SELECT
    USING (
        tenant_id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_ACCOUNT_MANAGER')
    );

-- F. Benchmarks Policies (Read-Only for Authenticated Users, Write Denied via RLS)
CREATE POLICY benchmarks_read_policy ON benchmarks
    FOR SELECT
    USING (true);

-- G. Credentials Vault Policies (Only Tenant Admins & Agency DevOps)
CREATE POLICY tenant_credentials_policy ON credentials
    FOR ALL
    USING (
        tenant_id = get_current_tenant_id()
        OR
        get_current_user_role() IN ('AGENCY_OWNER', 'AGENCY_DEVOPS')
    );
