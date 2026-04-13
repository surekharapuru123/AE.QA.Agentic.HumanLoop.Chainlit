import * as dotenv from 'dotenv';
dotenv.config();

export interface EnvironmentConfig {
  name: string;
  baseURL: string;
  timeout: number;
  credentials: {
    email: string;
    password: string;
  };
}

export interface EnvironmentDetails {
  base_url: string | null;
  credentials: {
    email: string;
    password: string;
  } | null;
}

const environments: Record<string, EnvironmentConfig> = {
  'gps-qa3': {
    name: 'GPS QA3',
    baseURL: process.env.BASE_URL || 'https://qa3.gps.aegm.com',
    timeout: 30000,
    credentials: {
      email: process.env.GPS_EMAIL || 'qaauto.test@aenetworks.com',
      password: process.env.GPS_PASSWORD || 'Test@123',
    },
  },
  'gps-qa2': {
    name: 'GPS QA2',
    baseURL: process.env.BASE_URL || 'https://qa2.gps.aegm.com',
    timeout: 30000,
    credentials: {
      email: process.env.GPS_EMAIL || 'qaauto.test@aenetworks.com',
      password: process.env.GPS_PASSWORD || 'Test@123',
    },
  },
};

export function getEnvironment(env?: string): EnvironmentConfig | undefined {
  const envName = env || process.env.TEST_ENV || 'gps-qa3';
  return environments[envName];
}

/**
 * Try to find a matching environment from Jira labels like "qa3", "gps-qa3", "staging".
 */
export function findEnvironmentByLabel(labels: string[]): EnvironmentConfig | undefined {
  for (const label of labels) {
    const normalized = label.toLowerCase().trim();
    if (environments[normalized]) return environments[normalized];
    for (const [key, config] of Object.entries(environments)) {
      if (normalized.includes(key) || key.includes(normalized)) return config;
    }
  }
  return undefined;
}

/**
 * Resolve environment details with a 3-tier fallback:
 * 1. Jira issue (planner output `environment_details`)
 * 2. Config environments (by env name or Jira labels)
 * 3. Returns null fields so the caller can prompt the user
 */
export function resolveEnvironment(
  plannerEnvDetails: EnvironmentDetails | null,
  jiraLabels: string[] = [],
  envName?: string,
): { baseURL: string | null; email: string | null; password: string | null; source: string } {
  if (plannerEnvDetails?.base_url && plannerEnvDetails?.credentials?.email) {
    return {
      baseURL: plannerEnvDetails.base_url,
      email: plannerEnvDetails.credentials.email,
      password: plannerEnvDetails.credentials.password,
      source: 'jira',
    };
  }

  const configEnv = getEnvironment(envName) ?? findEnvironmentByLabel(jiraLabels);
  if (configEnv) {
    return {
      baseURL: plannerEnvDetails?.base_url || configEnv.baseURL,
      email: plannerEnvDetails?.credentials?.email || configEnv.credentials.email,
      password: plannerEnvDetails?.credentials?.password || configEnv.credentials.password,
      source: plannerEnvDetails?.base_url || plannerEnvDetails?.credentials ? 'jira+config' : 'config',
    };
  }

  return {
    baseURL: plannerEnvDetails?.base_url || null,
    email: plannerEnvDetails?.credentials?.email || null,
    password: plannerEnvDetails?.credentials?.password || null,
    source: 'none',
  };
}

export function hasMissingEnvironmentDetails(resolved: {
  baseURL: string | null;
  email: string | null;
  password: string | null;
}): string[] {
  const missing: string[] = [];
  if (!resolved.baseURL) missing.push('base_url');
  if (!resolved.email) missing.push('email');
  if (!resolved.password) missing.push('password');
  return missing;
}

export default environments;
