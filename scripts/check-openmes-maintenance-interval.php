<?php
// Local API integration check. All test events/tokens/audit rows are rolled back.
require '/var/www/html/vendor/autoload.php';
$app = require '/var/www/html/bootstrap/app.php';
$app->instance('request', Illuminate\Http\Request::create('http://localhost:8092'));
$kernel = $app->make(Illuminate\Contracts\Http\Kernel::class);
$kernel->bootstrap();

use App\Models\{Line, MaintenanceEvent, User};
use Carbon\Carbon;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

function ensure($condition, $message) {
    if (!$condition) throw new RuntimeException($message);
}
ensure(config('app.url') === 'http://localhost:8092', 'Only the isolated local OpenMES may be checked');
ensure(DB::getDatabaseName() === 'openmes', 'Unexpected database');
ensure(DB::transactionLevel() === 0, 'Unexpected existing transaction');
$before = MaintenanceEvent::count();
$checks = [];
DB::beginTransaction();
try {
    $user = User::all()->first(fn ($user) => $user->hasRole('Admin'));
    $line = Line::where('code', 'A4S-FESTO')->firstOrFail();
    ensure((bool) $user, 'Expected a local administrator');
    $token = $user->createToken('interval-rollback-test')->plainTextToken;
    $call = function ($method, $path, $body = []) use ($kernel, $token) {
        $request = Request::create('http://localhost:8092/api/v1/'.$path, $method, [], [], [], [
            'HTTP_AUTHORIZATION' => 'Bearer '.$token, 'HTTP_ACCEPT' => 'application/json',
            'CONTENT_TYPE' => 'application/json',
        ], json_encode($body));
        $response = $kernel->handle($request);
        return [$response->getStatusCode(), json_decode($response->getContent(), true)];
    };
    $start = Carbon::now(config('app.timezone'))->addDay()->startOfHour();
    $end = $start->copy()->addMinutes(15);
    $base = ['title' => 'A4S interval rollback verification', 'event_type' => 'inspection',
        'line_id' => $line->id, 'scheduled_at' => $start->toIso8601String()];
    [$status] = $call('POST', 'maintenance-events', $base);
    ensure($status === 422, 'Creation must reject a missing planned end');
    $checks[] = 'missing_end_rejected';
    [$status] = $call('POST', 'maintenance-events', $base + ['scheduled_end_at' => $start->toIso8601String()]);
    ensure($status === 422, 'Creation must reject an empty interval');
    $checks[] = 'empty_interval_rejected';
    [$status, $created] = $call('POST', 'maintenance-events', $base + ['scheduled_end_at' => $end->toIso8601String()]);
    ensure($status === 201, 'Valid interval creation failed');
    $id = $created['data']['id'];
    [$status, $read] = $call('GET', 'maintenance-events/'.$id);
    ensure($status === 200 && Carbon::parse($read['data']['scheduled_at'])->equalTo($start)
        && Carbon::parse($read['data']['scheduled_end_at'])->equalTo($end), 'Both persisted instants must match');
    $checks[] = '15_minute_interval_read_back';
    $newEnd = $start->copy()->addMinutes(45);
    [$status] = $call('PATCH', 'maintenance-events/'.$id, ['scheduled_end_at' => $newEnd->toIso8601String()]);
    ensure($status === 200 && MaintenanceEvent::findOrFail($id)->scheduled_end_at->equalTo($newEnd), 'End-only update failed');
    $checks[] = 'end_only_update_persisted';
    [$status] = $call('PATCH', 'maintenance-events/'.$id, ['scheduled_at' => $newEnd->copy()->addMinute()->toIso8601String()]);
    ensure($status === 422 && MaintenanceEvent::findOrFail($id)->scheduled_at->equalTo($start), 'Invalid start-only update must be rejected');
    [$status] = $call('PATCH', 'maintenance-events/'.$id, ['scheduled_end_at' => $start->copy()->subMinute()->toIso8601String()]);
    ensure($status === 422, 'Invalid end-only update must be rejected');
    $checks[] = 'invalid_partial_updates_rejected';
    [$status, $board] = $call('GET', 'schedule/board?view_mode=hourly&start_date='.$start->toDateString().'&line_id='.$line->id);
    $event = collect($board['data']['maintenanceEvents'] ?? [])->firstWhere('id', $id);
    ensure($status === 200 && $event && $event['duration_minutes'] === 45, 'Planner must use the persisted duration');
    $checks[] = 'planner_uses_45_minute_duration';
} finally {
    while (DB::transactionLevel() > 0) DB::rollBack();
}
ensure(MaintenanceEvent::count() === $before, 'Test events must not remain');
echo json_encode(['passed' => count($checks), 'checks' => $checks, 'test_records_retained' => false]).PHP_EOL;
