<?php
namespace App\Http\Controllers\Api\V1;

use App\Http\Controllers\Controller;
use App\Models\{WorkOrder, MaintenanceEvent, Line, ProductType, Shift, ScheduleChangeLog};
use Carbon\Carbon;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/** Only enabled for an explicitly configured, isolated demo database. */
class DemoResetController extends Controller
{
    private function assertRows($actual, array $expected, array $fields): void
    {
        abort_unless($actual->count() === count($expected), 409, 'Demo scope changed');
        $indexed = collect($expected)->keyBy('id');
        foreach ($actual as $row) {
            $approved = $indexed->get($row->id);
            abort_unless($approved !== null, 409, 'Demo resource changed');
            foreach ($fields as $field) {
                $same = $field === 'produced_qty'
                    ? (float) $row->{$field} === (float) ($approved[$field] ?? -1)
                    : (string) $row->{$field} === (string) ($approved[$field] ?? '');
                abort_unless($same, 409, 'Demo resource changed');
            }
            abort_unless(!empty($approved['updated_at']) &&
                $row->updated_at->format('U.u') === Carbon::parse($approved['updated_at'])->format('U.u'),
                409, 'Demo resource version changed');
        }
    }

    public function archive(Request $request)
    {
        $key = (string) env('OPENMES_DEMO_RESET_KEY', '');
        abort_unless(env('OPENMES_DEMO_RESET_ENABLED', false) && strlen($key) >= 32 &&
            hash_equals($key, (string) $request->header('X-Demo-Reset-Key')), 403);
        abort_unless($request->user()->hasRole('Admin'), 403);
        $data = $request->validate([
            'orders' => ['present', 'array', 'max:1000'],
            'orders.*.id' => ['required', 'integer'],
            'orders.*.order_no' => ['required', 'string'],
            'orders.*.status' => ['required', 'string'],
            'orders.*.produced_qty' => ['required', 'numeric'],
            'orders.*.updated_at' => ['required', 'date'],
            'maintenance' => ['present', 'array', 'max:1000'],
            'maintenance.*.id' => ['required', 'integer'],
            'maintenance.*.status' => ['required', 'string'],
            'maintenance.*.updated_at' => ['required', 'date'],
            'line_ids' => ['required', 'array', 'min:1', 'max:2'],
            'line_ids.*' => ['required', 'integer', 'distinct'],
            'product_id' => ['required', 'integer'],
        ]);
        $result = DB::transaction(function () use ($data) {
            DB::statement("SET LOCAL lock_timeout = '5s'");
            DB::statement('LOCK TABLE work_orders, maintenance_events, lines, product_types, shifts, line_product_type, schedule_change_logs IN SHARE ROW EXCLUSIVE MODE');
            $lines = Line::whereIn('code', ['A4S-FESTO', 'A4S-BACKUP'])->get()->keyBy('code');
            abort_unless($lines->has('A4S-FESTO') && $lines->every(fn($l) => $l->is_active), 409, 'Demo lines missing or inactive');
            $ids = $lines->pluck('id')->sort()->values()->all();
            $approvedIds = $data['line_ids'];
            sort($approvedIds);
            abort_unless($ids === $approvedIds, 409, 'Demo line binding changed');
            $product = ProductType::where('code', 'A4S-DEMO-PART')->firstOrFail();
            abort_unless($product->id === $data['product_id'] && $product->is_active, 409, 'Demo product binding changed');
            $orders = WorkOrder::all();
            abort_if($orders->contains(fn($o) => !str_starts_with($o->order_no, 'A4S-') ||
                !in_array($o->line_id, $ids, true) || $o->status === 'IN_PROGRESS' || (float) $o->produced_qty > 0),
                409, 'Unrelated or started orders block demo reset');
            $maintenance = MaintenanceEvent::whereIn('line_id', $ids)->get();
            $this->assertRows($orders, $data['orders'], ['order_no', 'status', 'produced_qty']);
            $this->assertRows($maintenance, $data['maintenance'], ['status']);
            ScheduleChangeLog::whereIn('work_order_id', $orders->pluck('id'))->delete();
            // Use OpenMES model hooks to retain deletion attribution and cascade
            // soft deletes to dependent records; never truncate business tables.
            foreach ($orders as $order) $order->delete();
            foreach ($maintenance as $event) $event->delete();
            $lines['A4S-FESTO']->update(['name' => 'Festo CP Lab · Housing Cell 1']);
            // Retire the old virtual resource after archiving its demo records.
            if ($legacy = $lines->get('A4S-BACKUP')) {
                foreach (Shift::where('line_id', $legacy->id)->get() as $shift) $shift->delete();
                foreach (ProductType::all() as $type) $type->lines()->detach($legacy->id);
                $legacy->delete();
            }
            $ids = [$lines['A4S-FESTO']->id];
            $product->update(['name' => 'Phone housing · aluminium']);
            $product->lines()->syncWithoutDetaching($ids);
            foreach ($ids as $line) {
                foreach ([['D','06:00','18:00'],['N','18:00','06:00']] as [$code,$start,$end]) {
                    Shift::updateOrCreate(['code' => "A4S-$line-$code"], [
                        'name' => "Housing $code", 'start_time' => $start, 'end_time' => $end,
                        'days_of_week' => [1,2,3,4,5,6,7], 'line_id' => $line, 'is_active' => true,
                    ]);
                }
            }
            return ['line_id' => $lines['A4S-FESTO']->id,
                'product_id' => $product->id, 'archived_orders' => $orders->count(),
                'archived_maintenance' => $maintenance->count()];
        });
        return response()->json(['data' => $result]);
    }
}
