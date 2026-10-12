import QtQuick
import qs.Common

QtObject {
    function check(done) {
        Proc.runCommand("headphones.depCheck", ["sh", "-c", "command -v python3 && command -v busctl"], (stdout, exitCode) => {
            if (exitCode === 0) {
                done(null);
                return;
            }
            done({
                "title": I18n.trFor("headphones", "Python 3 and busctl are required"),
                "details": I18n.trFor("headphones", "The plugin talks to the headset through a small Python helper and reads device details from BlueZ with busctl (part of systemd). Install python3, then re-enable the plugin.")
            });
        });
    }
}
