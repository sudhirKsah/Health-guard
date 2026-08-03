package space.prava.healthguard;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import com.getcapacitor.JSArray;
import java.util.Calendar;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONObject;

public final class MedicineAlarmScheduler {
    static final String ACTION = "space.prava.healthguard.MEDICINE_ALARM";
    private static final String PREFERENCES = "medicine_alarm_schedule";
    private static final String IDS = "ids";

    private MedicineAlarmScheduler() {}

    public static void sync(Context context, JSArray reminders) throws Exception {
        SharedPreferences preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        Set<String> priorIds = preferences.getStringSet(IDS, new HashSet<>());
        for (String priorId : priorIds) {
            cancel(context, Integer.parseInt(priorId));
        }

        Set<String> nextIds = new HashSet<>();
        for (int index = 0; index < reminders.length(); index++) {
            JSONObject reminder = reminders.getJSONObject(index);
            int id = reminder.getInt("id");
            schedule(context, id, reminder.getInt("hour"), reminder.getInt("minute"));
            nextIds.add(Integer.toString(id));
        }
        preferences.edit().putStringSet(IDS, nextIds).apply();
    }

    static void schedule(Context context, int id, int hour, int minute) {
        Calendar next = Calendar.getInstance();
        next.set(Calendar.HOUR_OF_DAY, hour);
        next.set(Calendar.MINUTE, minute);
        next.set(Calendar.SECOND, 0);
        next.set(Calendar.MILLISECOND, 0);
        if (!next.after(Calendar.getInstance())) {
            next.add(Calendar.DAY_OF_YEAR, 1);
        }

        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pendingIntent = pendingIntent(context, id, hour, minute);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !alarmManager.canScheduleExactAlarms()) {
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next.getTimeInMillis(), pendingIntent);
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next.getTimeInMillis(), pendingIntent);
        } else {
            alarmManager.setExact(AlarmManager.RTC_WAKEUP, next.getTimeInMillis(), pendingIntent);
        }
    }

    static void cancel(Context context, int id) {
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pendingIntent = pendingIntent(context, id, 0, 0);
        alarmManager.cancel(pendingIntent);
        pendingIntent.cancel();
    }

    private static PendingIntent pendingIntent(Context context, int id, int hour, int minute) {
        Intent intent = new Intent(context, MedicineAlarmReceiver.class)
            .setAction(ACTION)
            .putExtra("id", id)
            .putExtra("hour", hour)
            .putExtra("minute", minute);
        return PendingIntent.getBroadcast(
            context,
            id,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }
}
