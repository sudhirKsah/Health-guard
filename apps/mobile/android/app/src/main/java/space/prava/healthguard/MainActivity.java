package space.prava.healthguard;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Capacitor reads custom plugin registrations while BridgeActivity is created.
        // Register first; registering after super leaves the JS bridge unaware of it.
        registerPlugin(MedicineAlarmPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
