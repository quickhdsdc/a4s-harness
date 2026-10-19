import {test} from 'node:test'
import assert from 'node:assert/strict'
import {weeklySlot, weeklyPlacements, onMonthlyDay, hourlyLanes} from '../_others/OpenMes-main/packages/ui/src/lib/planner.ts'

const order = {id:14,line_id:1,due_date:'2026-09-28',shift_number:null,
  end_date:null,end_shift_number:null,placements:[],
  planned_start_at:'2026-10-01T13:45:00+02:00',planned_end_at:'2026-10-01T14:30:00+02:00'}
const days = ['2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02'].map(date=>({date,isWeekend:false}))

test('Rescheduled order occupies Thursday in weekly, monthly and hourly views',()=>{
  assert.equal(weeklySlot(order,2).date,'2026-10-01')
  const block=weeklyPlacements([order],days,2,1).items[0]
  assert.equal(Math.floor(block.startCol/2),3)
  assert.equal(Math.floor(block.endCol/2),3)
  assert.equal(onMonthlyDay(order,'2026-09-28',28,9),false)
  assert.equal(onMonthlyDay(order,'2026-10-01',1,10),true)
  assert.equal(hourlyLanes([order],1,'2026-09-28').items.length,0)
  assert.equal(hourlyLanes([order],1,'2026-10-01').items.length,1)
  assert.equal(order.due_date,'2026-09-28')
})
test('Coarse orders retain legacy date and shift placement',()=>{
  assert.deepEqual(weeklySlot({...order,planned_start_at:null,planned_end_at:null,shift_number:1},2),{date:'2026-09-28',shift:1})
})
test('Exact midnight end does not occupy the following day',()=>{
  const block=weeklyPlacements([{...order,planned_end_at:'2026-10-02T00:00:00+02:00'}],days,2,1).items[0]
  assert.equal(Math.floor(block.endCol/2),3)
})
test('Extra segments retain their independent coarse placements',()=>{
  const blocks=weeklyPlacements([{...order,placements:[{id:90,line_id:2,due_date:'2026-09-29',shift_number:1}]}],days,2,2).items
  assert.equal(blocks[0].startCol,2)
})
