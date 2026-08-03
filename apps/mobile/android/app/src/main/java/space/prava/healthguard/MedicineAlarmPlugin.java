package space.prava.healthguard;

import com.getcapacitor.JSArray;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "MedicineAlarm")
public class MedicineAlarmPlugin extends Plugin {
    @com.getcapacitor.PluginMethod
    public void sync(PluginCall call) {
        JSArray reminders = call.getArray("reminders");
        if (reminders == null) {
            call.reject("reminders is required");
            return;
        }

        try {
            MedicineAlarmScheduler.sync(getContext(), reminders);
            call.resolve();
        } catch (Exception error) {
            call.reject("Could not schedule medicine alarm", error);
        }
    }
}
