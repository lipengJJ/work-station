/**
 * 笔记按发布时间（upload_time，形如 "2026-07-26 18:44:14"）降序分组：
 * 最近一周(0-7天) / 最近一个月(7-30天) / 最近半年(30-180天) / 更早(>180天)。
 * 时间解析失败的笔记归到"更早"，不让它们插在近期分组里干扰排序。
 */

export interface NoteTimeGroup<T> {
  label: string;
  notes: T[];
}

const ONE_DAY_MS = 24 * 60 * 60 * 1000;
const ONE_WEEK_MS = 7 * ONE_DAY_MS;
const ONE_MONTH_MS = 30 * ONE_DAY_MS;
const HALF_YEAR_MS = 180 * ONE_DAY_MS;

function parseUploadTime(uploadTime: string): number {
  if (!uploadTime) return Number.NaN;
  // 后端存的是 "YYYY-MM-DD HH:mm:ss"，不带时区——换成 "T" 分隔让 Date 按本地时间解析，
  // 和浏览器本地时间的 now 比较时口径一致（差个原始发布时区的偏移，分组用途下可以接受）。
  const time = new Date(uploadTime.replace(' ', 'T')).getTime();
  return Number.isNaN(time) ? Number.NaN : time;
}

export function groupNotesByRecency<T extends { upload_time: string }>(
  notes: T[],
  now: number = Date.now(),
): Array<NoteTimeGroup<T>> {
  const withTime = notes.map((note) => ({ note, time: parseUploadTime(note.upload_time) }));
  withTime.sort((a, b) => {
    if (Number.isNaN(a.time)) return 1;
    if (Number.isNaN(b.time)) return -1;
    return b.time - a.time;
  });

  const week: T[] = [];
  const month: T[] = [];
  const halfYear: T[] = [];
  const older: T[] = [];

  for (const { note, time } of withTime) {
    if (Number.isNaN(time)) {
      older.push(note);
      continue;
    }
    const age = now - time;
    if (age <= ONE_WEEK_MS) {
      week.push(note);
    } else if (age <= ONE_MONTH_MS) {
      month.push(note);
    } else if (age <= HALF_YEAR_MS) {
      halfYear.push(note);
    } else {
      older.push(note);
    }
  }

  const groups: Array<NoteTimeGroup<T>> = [];
  if (week.length) groups.push({ label: '最近一周', notes: week });
  if (month.length) groups.push({ label: '最近一个月', notes: month });
  if (halfYear.length) groups.push({ label: '最近半年', notes: halfYear });
  if (older.length) groups.push({ label: '更早', notes: older });
  return groups;
}
