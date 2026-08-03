package space.prava.healthguard;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.res.AssetFileDescriptor;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.os.Build;

public class MedicineAlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        int id = intent.getIntExtra("id", 0);
        int hour = intent.getIntExtra("hour", 8);
        int minute = intent.getIntExtra("minute", 0);
        MedicineAlarmScheduler.schedule(context, id, hour, minute);

        PendingResult pendingResult = goAsync();
        Thread playback = new Thread(() -> play(context.getApplicationContext(), pendingResult));
        playback.start();
    }

    private void play(Context context, PendingResult pendingResult) {
        MediaPlayer player = new MediaPlayer();
        try (AssetFileDescriptor audio = context.getResources().openRawResourceFd(R.raw.medicine_reminder)) {
            if (audio == null) {
                pendingResult.finish();
                return;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                player.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build());
            }
            player.setDataSource(audio.getFileDescriptor(), audio.getStartOffset(), audio.getLength());
            player.setOnCompletionListener(completed -> {
                completed.release();
                pendingResult.finish();
            });
            player.setOnErrorListener((failed, what, extra) -> {
                failed.release();
                pendingResult.finish();
                return true;
            });
            player.prepare();
            player.start();
        } catch (Exception error) {
            player.release();
            pendingResult.finish();
        }
    }
}
