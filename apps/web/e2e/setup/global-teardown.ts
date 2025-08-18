/**
 * Global Test Teardown for Ultra-Enterprise Security Testing - Task 3.15
 * 
 * Cleans up test infrastructure resources including:
 * - Mock services (OIDC, Email, SMS)
 * - Test database cleanup
 * - Security scanning tool cleanup
 */

import { globalTeardown as teardownFunction } from './global-setup'

// Re-export the teardown function from global-setup
export default teardownFunction