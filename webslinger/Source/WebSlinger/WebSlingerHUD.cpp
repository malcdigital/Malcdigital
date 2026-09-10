#include "WebSlingerHUD.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "WebShooterComponent.h"
#include "WebSlingerCharacter.h"
#include "WebSlingerMovementComponent.h"

void AWebSlingerHUD::DrawHUD()
{
	Super::DrawHUD();

	if (!Canvas)
	{
		return;
	}

	const float CenterX = Canvas->SizeX * 0.5f;
	const float CenterY = Canvas->SizeY * 0.5f;

	const AWebSlingerCharacter* Char = Cast<AWebSlingerCharacter>(GetOwningPawn());
	if (!Char)
	{
		DrawReticle(CenterX, CenterY, IdleColor, false);
		return;
	}

	const UWebShooterComponent* Shooter = Char->GetWebShooter();
	const UWebSlingerMovementComponent* Move = Char->GetSlingerMovement();

	const bool bAttached = Move && Move->HasWeb();
	const bool bHasTarget = Shooter && Shooter->HasTargetInSight();

	FLinearColor Color = IdleColor;
	if (bAttached)      { Color = AttachedColor; }
	else if (bHasTarget) { Color = TargetColor; }

	// While attached the anchor is a fixed world point that slides across the
	// screen. Drawing the reticle there instead of at screen centre lets the
	// player see the pivot they are swinging around.
	float ReticleX = CenterX;
	float ReticleY = CenterY;
	if (bAttached && Shooter)
	{
		const FVector Screen = Project(Shooter->GetCurrentTarget());
		if (Screen.Z > 0.f)
		{
			ReticleX = Screen.X;
			ReticleY = Screen.Y;
		}
	}

	DrawReticle(ReticleX, ReticleY, Color, bAttached || bHasTarget);

	if (bAttached && (ReticleX != CenterX || ReticleY != CenterY))
	{
		DrawReticle(CenterX, CenterY, IdleColor, false);
	}

	if (bShowSpeedReadout && Move)
	{
		DrawSpeedBar(Char->GetVelocity().Size(), Move->MaxSwingSpeed);
	}
}

void AWebSlingerHUD::DrawReticle(float CenterX, float CenterY, const FLinearColor& Color, bool bLocked)
{
	const float Gap = bLocked ? ReticleSize * 0.4f : ReticleSize * 0.9f;
	const float Arm = ReticleSize;
	const float Thickness = bLocked ? 2.f : 1.f;

	DrawLine(CenterX - Gap - Arm, CenterY, CenterX - Gap, CenterY, Color, Thickness);
	DrawLine(CenterX + Gap, CenterY, CenterX + Gap + Arm, CenterY, Color, Thickness);
	DrawLine(CenterX, CenterY - Gap - Arm, CenterX, CenterY - Gap, Color, Thickness);
	DrawLine(CenterX, CenterY + Gap, CenterX, CenterY + Gap + Arm, Color, Thickness);

	if (bLocked)
	{
		// Diamond, so a lock is distinguishable at a glance and in peripheral
		// vision, not just by colour.
		const float D = ReticleSize * 0.55f;
		DrawLine(CenterX, CenterY - D, CenterX + D, CenterY, Color, Thickness);
		DrawLine(CenterX + D, CenterY, CenterX, CenterY + D, Color, Thickness);
		DrawLine(CenterX, CenterY + D, CenterX - D, CenterY, Color, Thickness);
		DrawLine(CenterX - D, CenterY, CenterX, CenterY - D, Color, Thickness);
	}
}

void AWebSlingerHUD::DrawSpeedBar(float Speed, float MaxSpeed)
{
	const float BarWidth = FMath::Min(320.f, Canvas->SizeX * 0.25f);
	const float BarHeight = 4.f;
	const float X = Canvas->SizeX * 0.5f - BarWidth * 0.5f;
	const float Y = Canvas->SizeY - 70.f;

	const float Alpha = FMath::Clamp(Speed / FMath::Max(1.f, MaxSpeed), 0.f, 1.f);

	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.35f), X, Y, BarWidth, BarHeight);
	DrawRect(FLinearColor::LerpUsingHSV(AttachedColor, TargetColor, Alpha), X, Y, BarWidth * Alpha, BarHeight);

	// km/h, because cm/s means nothing to anyone.
	const FString Readout = FString::Printf(TEXT("%.0f km/h"), Speed * 0.036f);
	DrawText(Readout, FLinearColor(1.f, 1.f, 1.f, 0.7f), X, Y + 10.f, GEngine ? GEngine->GetMediumFont() : nullptr, 1.f);
}
