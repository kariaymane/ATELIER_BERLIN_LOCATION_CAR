package com.example

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.example.ui.components.FleetCountCard
import com.example.ui.components.OperationalStatCard
import com.example.ui.theme.MyApplicationTheme
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = RobolectricDeviceQualifiers.Pixel8, sdk = [36])
class GreetingScreenshotTest {

  @get:Rule val composeTestRule = createComposeRule()

  @Test
  fun operational_stat_card_screenshot() {
    composeTestRule.setContent {
      MyApplicationTheme {
        OperationalStatCard(
          label = "Aujourd'hui",
          value = "12",
          subtitle = "réservations"
        )
      }
    }

    composeTestRule.onRoot().captureRoboImage(filePath = "src/test/screenshots/stat_card.png")
  }

  @Test
  fun fleet_count_card_screenshot() {
    composeTestRule.setContent {
      MyApplicationTheme {
        FleetCountCard(
          title = "Prêts à louer",
          count = 65,
          icon = Icons.Default.DirectionsCar
        )
      }
    }

    composeTestRule.onRoot().captureRoboImage(filePath = "src/test/screenshots/fleet_card.png")
  }
}
