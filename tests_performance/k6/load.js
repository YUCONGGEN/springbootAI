import http from 'k6/http';
import ws from 'k6/ws';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const profile = (__ENV.SPRINGPY_PROFILE || 'smoke').toLowerCase();
const workload = (__ENV.SPRINGPY_WORKLOAD || 'mixed').toLowerCase();
const baseUrl = (__ENV.SPRINGPY_BASE_URL || 'http://app:8080').replace(/\/$/, '');

function intEnv(name, fallback) {
  const value = Number.parseInt(__ENV[name] || '', 10);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function floatEnv(name, fallback) {
  const value = Number.parseFloat(__ENV[name] || '');
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function arrivalScenario(rate, duration) {
  return {
    executor: 'constant-arrival-rate',
    exec: 'runWorkload',
    rate,
    timeUnit: '1s',
    duration,
    preAllocatedVUs: intEnv('SPRINGPY_PREALLOCATED_VUS', Math.max(10, Math.ceil(rate / 2))),
    maxVUs: intEnv('SPRINGPY_MAX_VUS', Math.max(50, rate * 2)),
    gracefulStop: '30s',
  };
}

function profileScenario() {
  if (profile === 'smoke') {
    return arrivalScenario(intEnv('SPRINGPY_RATE', 5), __ENV.SPRINGPY_DURATION || '20s');
  }
  if (profile === 'baseline') {
    return arrivalScenario(intEnv('SPRINGPY_RATE', 100), __ENV.SPRINGPY_DURATION || '10m');
  }
  if (profile === 'soak') {
    return arrivalScenario(intEnv('SPRINGPY_RATE', 100), __ENV.SPRINGPY_DURATION || '2h');
  }
  if (profile === 'stress') {
    const startRate = intEnv('SPRINGPY_START_RPS', 50);
    const targetRate = intEnv('SPRINGPY_TARGET_RPS', 500);
    const stageDuration = __ENV.SPRINGPY_STAGE_DURATION || '2m';
    return {
      executor: 'ramping-arrival-rate',
      exec: 'runWorkload',
      startRate,
      timeUnit: '1s',
      preAllocatedVUs: intEnv('SPRINGPY_PREALLOCATED_VUS', Math.max(25, startRate)),
      maxVUs: intEnv('SPRINGPY_MAX_VUS', Math.max(200, targetRate * 2)),
      stages: [
        { duration: stageDuration, target: targetRate },
        { duration: stageDuration, target: targetRate },
        { duration: stageDuration, target: Math.max(startRate, Math.floor(targetRate / 2)) },
        { duration: '30s', target: 0 },
      ],
      gracefulStop: '30s',
    };
  }
  throw new Error(`Unknown SPRINGPY_PROFILE: ${profile}`);
}

const p95Ms = intEnv('SPRINGPY_P95_MS', 500);
const p99Ms = intEnv('SPRINGPY_P99_MS', 1000);
const failRate = floatEnv('SPRINGPY_FAIL_RATE', 0.01);
const checkRate = floatEnv('SPRINGPY_CHECK_RATE', 0.99);
const maxDropped = intEnv('SPRINGPY_MAX_DROPPED', 0);
const maxOverload = intEnv('SPRINGPY_MAX_OVERLOAD', 0);

export const options = {
  scenarios: { springpy: profileScenario() },
  thresholds: {
    checks: [`rate>${checkRate}`],
    http_req_failed: [`rate<${failRate}`],
    http_req_duration: [`p(95)<${p95Ms}`, `p(99)<${p99Ms}`],
    dropped_iterations: [`count<=${maxDropped}`],
    overload_responses: [`count<=${maxOverload}`],
    'springpy_endpoint_duration{endpoint:async}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:sync}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:gateway}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:validation}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:cache}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:csv}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:jpa}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:conditional}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:data}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:datasource}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:txevent}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:config}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:i18n}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:actuator}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:swagger}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:websocket}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:messaging}': [`p(95)<${p95Ms}`],
    'springpy_endpoint_duration{endpoint:seata}': [`p(95)<${p95Ms}`],
  },
  userAgent: 'springpy-k6/1.0',
  noConnectionReuse: false,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

const endpointDuration = new Trend('springpy_endpoint_duration', true);
const overloadResponses = new Counter('overload_responses');

const paths = {
  async: __ENV.SPRINGPY_ASYNC_PATH || '/benchmark/async',
  sync: __ENV.SPRINGPY_SYNC_PATH || '/benchmark/sync?delay_ms=20',
  gateway: __ENV.SPRINGPY_GATEWAY_PATH || '/gateway/benchmark/upstream',
  echo: __ENV.SPRINGPY_ECHO_PATH || '/benchmark/echo',
  cpu: __ENV.SPRINGPY_CPU_PATH || '/benchmark/cpu?iterations=1000',
  validation: __ENV.SPRINGPY_VALIDATION_PATH || '/benchmark/validation',
  cache: __ENV.SPRINGPY_CACHE_PATH || '/benchmark/cache',
  csv: __ENV.SPRINGPY_CSV_PATH || `/benchmark/csv?rows=${intEnv('SPRINGPY_CSV_ROWS', 50)}`,
  jpa: __ENV.SPRINGPY_JPA_PATH || '/benchmark/jpa',
  conditional: __ENV.SPRINGPY_CONDITIONAL_PATH
    || `/benchmark/conditional?evaluations=${intEnv('SPRINGPY_CONDITIONAL_EVALUATIONS', 100)}`,
  data: __ENV.SPRINGPY_DATA_PATH
    || `/benchmark/data?rows=${intEnv('SPRINGPY_DATA_ROWS', 100)}`,
  datasource: __ENV.SPRINGPY_DATASOURCE_PATH || '/benchmark/datasource',
  txevent: __ENV.SPRINGPY_TX_EVENT_PATH || '/benchmark/tx-event',
  config: __ENV.SPRINGPY_CONFIG_PATH
    || `/benchmark/config-binding?bindings=${intEnv('SPRINGPY_BINDING_ITERATIONS', 25)}`,
  i18n: __ENV.SPRINGPY_I18N_PATH
    || `/benchmark/i18n?messages=${intEnv('SPRINGPY_I18N_MESSAGES', 100)}`,
  actuator: __ENV.SPRINGPY_ACTUATOR_PATH || '/actuator/beans',
  swagger: __ENV.SPRINGPY_SWAGGER_PATH || '/openapi.json',
  swagger_docs: __ENV.SPRINGPY_SWAGGER_DOCS_PATH || '/docs',
  swagger_redoc: __ENV.SPRINGPY_SWAGGER_REDOC_PATH || '/redoc',
  websocket: __ENV.SPRINGPY_WEBSOCKET_PATH || '/ws/benchmark-echo',
  messaging: __ENV.SPRINGPY_MESSAGING_PATH || '/ws/benchmark-app',
  custom: __ENV.SPRINGPY_CUSTOM_PATH || '/',
};

const expectedStatuses = (__ENV.SPRINGPY_EXPECTED_STATUS || '200')
  .split(',')
  .map((value) => Number.parseInt(value.trim(), 10));

function headers() {
  const result = { 'Content-Type': 'application/json' };
  if (__ENV.SPRINGPY_AUTH_TOKEN) {
    result.Authorization = `Bearer ${__ENV.SPRINGPY_AUTH_TOKEN}`;
  }
  return result;
}

function seataHeaders() {
  return {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    'X-Seata-Bridge-Token': __ENV.SPRINGPY_SEATA_BRIDGE_TOKEN || '',
  };
}

function runSeata() {
  const startedAt = Date.now();
  const begin = http.post(
    `${baseUrl}/api/v1/transactions`,
    JSON.stringify({
      timeoutMs: intEnv('SPRINGPY_SEATA_TIMEOUT_MS', 60000),
      name: `springpy-k6-${exec.scenario.iterationInTest}`,
      applicationId: __ENV.SPRINGPY_SEATA_APPLICATION_ID || 'springpy-k6',
      transactionGroup: __ENV.SPRINGPY_SEATA_TRANSACTION_GROUP || 'springpy_tx_group',
    }),
    { headers: seataHeaders(), tags: { endpoint: 'seata' } },
  );
  let xid = '';
  try {
    xid = begin.status === 200 ? String(begin.json('xid') || '') : '';
  } catch (_) {
    xid = '';
  }
  let finish = begin;
  if (xid) {
    const action = exec.scenario.iterationInTest % 10 === 0 ? 'rollback' : 'commit';
    finish = http.post(
      `${baseUrl}/api/v1/transactions/${encodeURIComponent(xid)}/${action}`,
      '{}',
      { headers: seataHeaders(), tags: { endpoint: 'seata' } },
    );
  }
  endpointDuration.add(Date.now() - startedAt, { endpoint: 'seata' });
  check(begin, { 'seata: begin succeeded': (res) => res.status === 200 && xid !== '' });
  check(finish, {
    'seata: phase two succeeded': (res) => {
      if (res.status !== 200) return false;
      try {
        return res.json('success') === true;
      } catch (_) {
        return false;
      }
    },
  });
}

function record(endpoint, response) {
  endpointDuration.add(response.timings.duration, { endpoint });
  if (response.status === 503) {
    overloadResponses.add(1, { endpoint });
  }
  check(response, {
    [`${endpoint}: expected HTTP status`]: (res) => expectedStatuses.includes(res.status),
    [`${endpoint}: Spring result is successful`]: (res) => {
      if (endpoint === 'custom' || res.status === 204) {
        return true;
      }
      const contentType = res.headers['Content-Type'] || '';
      if (!contentType.includes('application/json')) {
        return false;
      }
      try {
        const payload = res.json();
        return payload.code === undefined || payload.code === 200;
      } catch (_) {
        return false;
      }
    },
    [`${endpoint}: business invariant holds`]: (res) => {
      if (endpoint === 'custom' || res.status === 204) {
        return true;
      }
      try {
        const envelope = res.json();
        const data = envelope.data || envelope;
        if (endpoint === 'validation') {
          return data.kind === 'validation' && data.valid === true && data.fields === 4;
        }
        if (endpoint === 'cache') {
          return data.kind === 'cache' && data.consistent === true && data.cache_hit === true;
        }
        if (endpoint === 'csv') {
          return data.kind === 'csv' && data.round_trip === true && data.rows > 0;
        }
        if (endpoint === 'jpa') {
          return data.kind === 'jpa'
            && data.updated === true
            && data.conflict_detected === true
            && data.version === 1
            && data.transient_mapped === false;
        }
        if (endpoint === 'conditional') {
          return data.kind === 'conditional'
            && data.evaluations > 0
            && data.matched === data.evaluations;
        }
        if (endpoint === 'data') {
          return data.kind === 'data'
            && data.total === data.expected_total
            && data.page_size > 0
            && data.sorted === true
            && data.repository_entity === 'DataBenchmarkRecord'
            && data.transient_mapped === false;
        }
        if (endpoint === 'datasource') {
          return data.kind === 'datasource'
            && data.selected[0] === 'master'
            && data.selected[3] === 'report'
            && data.routed_to_slaves === true
            && data.returned === true
            && data.context_cleared === true;
        }
        if (endpoint === 'txevent') {
          return data.kind === 'tx_event'
            && JSON.stringify(data.commit_phases)
              === JSON.stringify(['before_commit', 'after_commit', 'after_completion'])
            && JSON.stringify(data.rollback_phases)
              === JSON.stringify(['after_rollback', 'after_completion'])
            && data.context_cleared === true;
        }
        if (endpoint === 'config') {
          return data.kind === 'config_binding'
            && data.bindings > 0
            && data.valid === true;
        }
        if (endpoint === 'i18n') {
          return data.kind === 'i18n'
            && data.messages === data.resolved
            && data.fallback === true;
        }
        if (endpoint === 'actuator') {
          return data.contexts
            && data.contexts.application
            && Object.keys(data.contexts.application.beans || {}).length > 0;
        }
        return true;
      } catch (_) {
        return false;
      }
    },
  });
}

function getEndpoint(endpoint) {
  const response = http.get(`${baseUrl}${paths[endpoint]}`, {
    headers: headers(),
    tags: { endpoint },
    timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
  });
  record(endpoint, response);
}

function recordSwaggerDocument(response) {
  endpointDuration.add(response.timings.duration, { endpoint: 'swagger' });
  if (response.status === 503) {
    overloadResponses.add(1, { endpoint: 'swagger' });
  }
  check(response, {
    'swagger: OpenAPI status is 200': (res) => res.status === 200,
    'swagger: OpenAPI document is valid': (res) => {
      try {
        const document = res.json();
        const pathsInDocument = Object.keys(document.paths || {});
        const benchmarkOperation = document.paths?.['/benchmark/data']?.get;
        const securitySchemes = document.components?.securitySchemes || {};
        return document.openapi
          && document.info?.title
          && document.info?.version
          && pathsInDocument.length > 0
          && benchmarkOperation?.tags?.includes('SpringBootAI Benchmark')
          && benchmarkOperation?.operationId === 'benchmarkData'
          && benchmarkOperation?.responses?.['200']?.description === 'Paged benchmark data'
          && benchmarkOperation?.security?.some((entry) => entry.BenchmarkBearer)
          && securitySchemes.BenchmarkBearer?.scheme === 'bearer';
      } catch (_) {
        return false;
      }
    },
  });
}

function runSwagger() {
  const openapi = http.get(`${baseUrl}${paths.swagger}`, {
    headers: headers(),
    tags: { endpoint: 'swagger' },
    timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
  });
  recordSwaggerDocument(openapi);

  for (const [name, path] of [
    ['Swagger UI', paths.swagger_docs],
    ['ReDoc', paths.swagger_redoc],
  ]) {
    const response = http.get(`${baseUrl}${path}`, {
      headers: headers(),
      tags: { endpoint: 'swagger' },
      timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
    });
    endpointDuration.add(response.timings.duration, { endpoint: 'swagger' });
    if (response.status === 503) {
      overloadResponses.add(1, { endpoint: 'swagger' });
    }
    check(response, {
      [`swagger: ${name} status is 200`]: (res) => res.status === 200,
      [`swagger: ${name} renders HTML`]: (res) => (
        (res.headers['Content-Type'] || '').includes('text/html')
        && (res.body || '').length > 100
      ),
    });
  }
}

function postEcho() {
  const body = JSON.stringify({ id: `${__VU}-${__ITER}`, value: 'springpy-load-test' });
  const response = http.post(`${baseUrl}${paths.echo}`, body, {
    headers: headers(),
    tags: { endpoint: 'echo' },
    timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
  });
  record('echo', response);
}

function postJson(endpoint, payload) {
  const response = http.post(`${baseUrl}${paths[endpoint]}`, JSON.stringify(payload), {
    headers: headers(),
    tags: { endpoint },
    timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
  });
  record(endpoint, response);
}

function postValidation() {
  postJson('validation', {
    name: `load-user-${__VU}-${__ITER}`,
    age: 30,
    email: `load-${__VU}-${__ITER}@example.test`,
    password: 'benchmark-password',
  });
}

function postCache() {
  postJson('cache', {
    id: (__VU * 100000000) + __ITER,
    value: `cache-${__VU}-${__ITER}`,
  });
}

function customRequest() {
  const method = (__ENV.SPRINGPY_CUSTOM_METHOD || 'GET').toUpperCase();
  const body = __ENV.SPRINGPY_CUSTOM_BODY || null;
  const response = http.request(method, `${baseUrl}${paths.custom}`, body, {
    headers: headers(),
    tags: { endpoint: 'custom' },
    timeout: __ENV.SPRINGPY_REQUEST_TIMEOUT || '5s',
  });
  record('custom', response);
}

function socketUrl(path) {
  return `${baseUrl.replace(/^http/, 'ws')}${path}`;
}

function recordSocket(endpoint, response, completed, startedAt) {
  endpointDuration.add(Date.now() - startedAt, { endpoint });
  check({ response, completed }, {
    [`${endpoint}: WebSocket upgraded`]: (result) => (
      result.response !== null && result.response.status === 101
    ),
    [`${endpoint}: message flow completed`]: (result) => result.completed === true,
  });
}

function runWebSocket() {
  const startedAt = Date.now();
  let completed = false;
  const response = ws.connect(
    socketUrl(paths.websocket),
    { headers: headers(), tags: { endpoint: 'websocket' } },
    (socket) => {
      socket.on('message', (message) => {
        if (message === 'ready') {
          socket.send('ping');
        } else if (message === 'echo:ping') {
          completed = true;
          socket.close();
        }
      });
      socket.setTimeout(() => socket.close(), intEnv('SPRINGPY_WEBSOCKET_TIMEOUT_MS', 3000));
    },
  );
  recordSocket('websocket', response, completed, startedAt);
}

function runMessaging() {
  const startedAt = Date.now();
  let state = 'bootstrap';
  let completed = false;
  const response = ws.connect(
    socketUrl(paths.messaging),
    { headers: headers(), tags: { endpoint: 'messaging' } },
    (socket) => {
      socket.on('open', () => {
        socket.send(JSON.stringify({
          action: 'subscribe',
          destination: '/topic/bootstrap',
        }));
      });
      socket.on('message', (message) => {
        let frame;
        try {
          frame = JSON.parse(message);
        } catch (_) {
          socket.close();
          return;
        }
        if (state === 'bootstrap' && frame.payload && frame.payload.ready === true) {
          state = 'echo';
          socket.send(JSON.stringify({
            action: 'message',
            destination: '/app/echo',
            payload: 'ping',
          }));
        } else if (
          state === 'echo'
          && frame.payload
          && frame.payload.echo === 'ping'
        ) {
          state = 'broadcast';
          socket.send(JSON.stringify({
            action: 'subscribe',
            destination: '/topic/benchmark',
          }));
          socket.send(JSON.stringify({
            action: 'message',
            destination: '/app/broadcast',
            payload: 'ping',
          }));
        } else if (
          state === 'broadcast'
          && frame.destination === '/topic/benchmark'
          && frame.payload
          && frame.payload.broadcast === 'ping'
        ) {
          completed = true;
          socket.close();
        }
      });
      socket.setTimeout(() => socket.close(), intEnv('SPRINGPY_WEBSOCKET_TIMEOUT_MS', 3000));
    },
  );
  recordSocket('messaging', response, completed, startedAt);
}

export function runWorkload() {
  if (workload === 'custom') {
    customRequest();
    return;
  }
  if (workload !== 'mixed') {
    if (workload === 'echo') {
      postEcho();
    } else if (workload === 'validation') {
      postValidation();
    } else if (workload === 'cache') {
      postCache();
    } else if (workload === 'websocket') {
      runWebSocket();
    } else if (workload === 'messaging') {
      runMessaging();
    } else if (workload === 'seata') {
      runSeata();
    } else if (workload === 'swagger') {
      runSwagger();
    } else {
      getEndpoint(workload);
    }
    return;
  }

  const bucket = exec.scenario.iterationInTest % 100;
  if (bucket < 15) {
    getEndpoint('async');
  } else if (bucket < 30) {
    getEndpoint('sync');
  } else if (bucket < 40) {
    getEndpoint('gateway');
  } else if (bucket < 45) {
    postEcho();
  } else if (bucket < 50) {
    postValidation();
  } else if (bucket < 55) {
    postCache();
  } else if (bucket < 60) {
    getEndpoint('csv');
  } else if (bucket < 65) {
    getEndpoint('jpa');
  } else if (bucket < 70) {
    getEndpoint('conditional');
  } else if (bucket < 75) {
    getEndpoint('data');
  } else if (bucket < 80) {
    getEndpoint('datasource');
  } else if (bucket < 85) {
    getEndpoint('txevent');
  } else if (bucket < 89) {
    getEndpoint('config');
  } else if (bucket < 93) {
    getEndpoint('i18n');
  } else if (bucket < 95) {
    getEndpoint('actuator');
  } else if (bucket < 96) {
    runSwagger();
  } else if (bucket < 98) {
    runWebSocket();
  } else {
    runMessaging();
  }
}

function metric(data, name, key) {
  const values = data.metrics[name] && data.metrics[name].values;
  return values && values[key] !== undefined ? values[key] : null;
}

export function handleSummary(data) {
  const report = {
    metadata: {
      generated_at: new Date().toISOString(),
      profile,
      workload,
      base_url: baseUrl,
      thresholds: { p95_ms: p95Ms, p99_ms: p99Ms, fail_rate: failRate },
    },
    result: {
      requests: metric(data, 'http_reqs', 'count'),
      request_rate: metric(data, 'http_reqs', 'rate'),
      failed_rate: metric(data, 'http_req_failed', 'rate'),
      p95_ms: metric(data, 'http_req_duration', 'p(95)'),
      p99_ms: metric(data, 'http_req_duration', 'p(99)'),
      dropped_iterations: metric(data, 'dropped_iterations', 'count'),
      overload_responses: metric(data, 'overload_responses', 'count'),
    },
    k6: data,
  };
  const outputPath = __ENV.SPRINGPY_RESULTS_FILE || '/results/summary.json';
  const line = [
    `SpringBootAI k6 ${profile}/${workload}`,
    `requests=${report.result.requests}`,
    `rps=${report.result.request_rate}`,
    `p95=${report.result.p95_ms}ms`,
    `p99=${report.result.p99_ms}ms`,
    `failed=${report.result.failed_rate}`,
    `dropped=${report.result.dropped_iterations}`,
    `overload=${report.result.overload_responses}`,
    `result=${outputPath}`,
  ].join(' | ');
  return { [outputPath]: JSON.stringify(report, null, 2), stdout: `${line}\n` };
}
