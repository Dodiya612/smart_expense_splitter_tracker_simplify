import { config } from '@/constants/config';
import { fastApiClient } from '@/services/api/fastApiClient';
import { ApiClient } from '@/services/api/types';
import { mockApiClient } from '@/services/mock/mockApiClient';

/**
 * Returns the active ApiClient instance based on application configuration.
 * Screens and feature hooks call this accessor rather than instantiating clients.
 */
export function getApiClient(): ApiClient {
  if (config.useMockApi) {
    return mockApiClient;
  }

  return fastApiClient;
}
