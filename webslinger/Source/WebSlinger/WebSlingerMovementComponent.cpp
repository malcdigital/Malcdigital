#include "WebSlingerMovementComponent.h"

#include "Components/CapsuleComponent.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"

UWebSlingerMovementComponent::UWebSlingerMovementComponent()
{
	MaxAcceleration = 2400.f;
	MaxWalkSpeed = 900.f;
	BrakingDecelerationWalking = 2400.f;
	JumpZVelocity = 950.f;
	AirControl = 0.55f;
	// Earth gravity feels floaty at these speeds; the physics settings raise it
	// and this scales it once more for the character alone.
	GravityScale = 1.15f;
	SetWalkableFloorAngle(52.f);
	bUseSeparateBrakingFriction = true;
}

// ---------------------------------------------------------------------------
// Control
// ---------------------------------------------------------------------------

bool UWebSlingerMovementComponent::BeginSwing(const FVector& InAnchor)
{
	if (!UpdatedComponent || !CharacterOwner)
	{
		return false;
	}

	const float Dist = FVector::Dist(UpdatedComponent->GetComponentLocation(), InAnchor);
	if (Dist < MinRopeLength || Dist > MaxRopeLength)
	{
		return false;
	}

	Anchor = InAnchor;
	// Taut on contact. Slack here would read as a delay, not as weight.
	RopeLength = Dist;
	bHasWeb = true;
	ReelInput = 0.f;

	SetMovementMode(MOVE_Custom, CMOVE_Swinging);
	return true;
}

void UWebSlingerMovementComponent::EndSwing(bool bBoost)
{
	if (!bHasWeb)
	{
		return;
	}
	bHasWeb = false;
	ReelInput = 0.f;

	// Only pay out the kick on an upward release. Letting go at the bottom of
	// the arc should keep the speed you earned, not hand out free height.
	if (bBoost && Velocity.Z > 0.f)
	{
		Velocity.Z += Velocity.Size() * ReleaseBoost;
		Velocity = Velocity.GetClampedToMaxSize(MaxSwingSpeed);
	}

	if (IsSwinging() && !bChangingMode)
	{
		TGuardValue<bool> Guard(bChangingMode, true);
		SetMovementMode(MOVE_Falling);
	}
}

bool UWebSlingerMovementComponent::BeginWallCrawl(const FHitResult& Surface)
{
	if (!UpdatedComponent || !CharacterOwner || !Surface.IsValidBlockingHit())
	{
		return false;
	}
	if (Surface.ImpactNormal.Z > MaxCrawlableFloorZ)
	{
		return false; // flat enough to just walk on
	}

	CrawlSurfaceNormal = Surface.ImpactNormal;
	// Keep whatever momentum still runs along the surface; dump the part that
	// went into it, which is now absorbed by sticking.
	Velocity = FVector::VectorPlaneProject(Velocity, CrawlSurfaceNormal);

	SetMovementMode(MOVE_Custom, CMOVE_WallCrawl);
	return true;
}

void UWebSlingerMovementComponent::EndWallCrawl()
{
	if (IsWallCrawling() && !bChangingMode)
	{
		TGuardValue<bool> Guard(bChangingMode, true);
		SetMovementMode(MOVE_Falling);
	}
}

float UWebSlingerMovementComponent::GetSwingLean() const
{
	if (!bHasWeb || !UpdatedComponent || !CharacterOwner)
	{
		return 0.f;
	}
	const FVector ToAnchor = (Anchor - UpdatedComponent->GetComponentLocation()).GetSafeNormal();
	if (ToAnchor.IsNearlyZero())
	{
		return 0.f;
	}
	const FVector Right = CharacterOwner->GetActorRightVector();
	return FMath::Clamp(FVector::DotProduct(Right, ToAnchor), -1.f, 1.f);
}

// ---------------------------------------------------------------------------
// UCharacterMovementComponent
// ---------------------------------------------------------------------------

float UWebSlingerMovementComponent::GetMaxSpeed() const
{
	if (MovementMode == MOVE_Custom)
	{
		switch (CustomMovementMode)
		{
		case CMOVE_Swinging:  return MaxSwingSpeed;
		case CMOVE_WallCrawl: return MaxCrawlSpeed;
		default: break;
		}
	}
	return Super::GetMaxSpeed();
}

bool UWebSlingerMovementComponent::CanAttemptJump() const
{
	// Jumping off a wall is the main way to break a crawl, so allow it there
	// even though a crawl is not "on the ground".
	return Super::CanAttemptJump() || IsWallCrawling();
}

#if UE_VERSION_OLDER_THAN(5, 4, 0)
bool UWebSlingerMovementComponent::DoJump(bool bReplayingMoves)
#else
bool UWebSlingerMovementComponent::DoJump(bool bReplayingMoves, float DeltaTime)
#endif
{
	if (IsWallCrawling() && CharacterOwner && CharacterOwner->CanJump())
	{
		// Push off the surface and up, so a wall jump clears the wall instead
		// of scraping back into it.
		const FVector Off = CrawlSurfaceNormal * WallJumpImpulse + FVector::UpVector * JumpZVelocity;
		EndWallCrawl();
		Velocity = FVector::VectorPlaneProject(Velocity, CrawlSurfaceNormal) + Off;
		return true;
	}

	if (IsSwinging())
	{
		// Space cuts the line rather than doing nothing mid-air.
		EndSwing(true);
		return true;
	}

#if UE_VERSION_OLDER_THAN(5, 4, 0)
	return Super::DoJump(bReplayingMoves);
#else
	return Super::DoJump(bReplayingMoves, DeltaTime);
#endif
}

void UWebSlingerMovementComponent::OnMovementModeChanged(EMovementMode PreviousMovementMode, uint8 PreviousCustomMode)
{
	Super::OnMovementModeChanged(PreviousMovementMode, PreviousCustomMode);

	const bool bLeftSwing = PreviousMovementMode == MOVE_Custom
		&& PreviousCustomMode == CMOVE_Swinging
		&& !IsSwinging();

	if (bLeftSwing)
	{
		bHasWeb = false;
		ReelInput = 0.f;
	}
}

void UWebSlingerMovementComponent::PhysCustom(float DeltaTime, int32 Iterations)
{
	switch (CustomMovementMode)
	{
	case CMOVE_Swinging:
		PhysSwinging(DeltaTime, Iterations);
		break;
	case CMOVE_WallCrawl:
		PhysWallCrawl(DeltaTime, Iterations);
		break;
	default:
		Super::PhysCustom(DeltaTime, Iterations);
		break;
	}
}

void UWebSlingerMovementComponent::FallOut(float DeltaTime, int32 Iterations)
{
	bHasWeb = false;
	TGuardValue<bool> Guard(bChangingMode, true);
	SetMovementMode(MOVE_Falling);
	StartNewPhysics(DeltaTime, Iterations);
}

// ---------------------------------------------------------------------------
// Swinging
// ---------------------------------------------------------------------------

void UWebSlingerMovementComponent::PhysSwinging(float DeltaTime, int32 Iterations)
{
	if (DeltaTime < MIN_TICK_TIME)
	{
		return;
	}
	if (!bHasWeb || !CharacterOwner || !UpdatedComponent)
	{
		FallOut(DeltaTime, Iterations);
		return;
	}

	RestorePreAdditiveRootMotionVelocity();

	FVector Loc = UpdatedComponent->GetComponentLocation();
	FVector ToAnchor = Anchor - Loc;
	float Dist = ToAnchor.Size();
	if (Dist < KINDA_SMALL_NUMBER)
	{
		FallOut(DeltaTime, Iterations);
		return;
	}
	FVector RopeDir = ToAnchor / Dist; // character -> anchor

	// 1. Gravity. This is the only thing that powers a swing at rest.
	Velocity += FVector(0.f, 0.f, GetGravityZ()) * DeltaTime;

	// 2. Steering. Project the thrust onto the plane perpendicular to the line
	//    so pushing "toward the anchor" cannot fight the constraint and jitter.
	const FVector InputDir = Acceleration.GetSafeNormal();
	if (!InputDir.IsNearlyZero())
	{
		const FVector Thrust = FVector::VectorPlaneProject(InputDir * SwingThrust, RopeDir);
		Velocity += Thrust * DeltaTime;
	}

	// 3. Line length. Manual reel wins; otherwise pump the pendulum the way a
	//    child does on a swing - stand up at the bottom, squat at the top.
	float LengthDelta = 0.f;
	if (!FMath::IsNearlyZero(ReelInput))
	{
		LengthDelta = -ReelInput * ReelSpeed * DeltaTime;
	}
	else if (bAutoPump)
	{
		const float Verticality = FVector::DotProduct(RopeDir, FVector::UpVector);
		LengthDelta = (Verticality > AutoPumpVerticality ? -1.f : 1.f) * AutoPumpSpeed * DeltaTime;
	}
	RopeLength = FMath::Clamp(RopeLength + LengthDelta, MinRopeLength, MaxRopeLength);

	// 4. Tension. A rope pulls, it never pushes: only act once the line is taut,
	//    and only on the component of velocity leaving the sphere.
	if (Dist >= RopeLength)
	{
		const float Outward = FVector::DotProduct(Velocity, -RopeDir);
		if (Outward > 0.f)
		{
			Velocity += RopeDir * Outward * (1.f + TensionRestitution);
		}
	}

	// 5. Drag and clamp.
	Velocity *= FMath::Clamp(1.f - SwingDrag * DeltaTime, 0.f, 1.f);
	Velocity = Velocity.GetClampedToMaxSize(MaxSwingSpeed);

	// 6. Move.
	Iterations++;
	bJustTeleported = false;
	const FVector Delta = Velocity * DeltaTime;
	const FQuat Rot = UpdatedComponent->GetComponentQuat();

	FHitResult Hit(1.f);
	SafeMoveUpdatedComponent(Delta, Rot, true, Hit);

	if (Hit.IsValidBlockingHit())
	{
		// Hitting a roof or a street mid-swing ends it; grazing a wall does not.
		if (Hit.ImpactNormal.Z >= GetWalkableFloorZ())
		{
			EndSwing(false);
			FallOut(DeltaTime, Iterations);
			return;
		}
		HandleImpact(Hit, DeltaTime, Delta);
		SlideAlongSurface(Delta, 1.f - Hit.Time, Hit.Normal, Hit, true);
	}

	// 7. Positional correction. Integration overshoots the sphere every frame;
	//    left uncorrected the line stretches and the arc goes soft. Pull back
	//    onto the constraint surface without touching velocity, so momentum
	//    survives the correction.
	Loc = UpdatedComponent->GetComponentLocation();
	ToAnchor = Anchor - Loc;
	Dist = ToAnchor.Size();
	if (Dist > RopeLength + 1.f)
	{
		RopeDir = ToAnchor / Dist;
		FHitResult CorrectionHit(1.f);
		SafeMoveUpdatedComponent(RopeDir * (Dist - RopeLength), Rot, true, CorrectionHit);
	}
}

// ---------------------------------------------------------------------------
// Wall crawling
// ---------------------------------------------------------------------------

bool UWebSlingerMovementComponent::TraceCrawlSurface(const FVector& From, const FVector& Dir, FHitResult& Out) const
{
	const UWorld* World = GetWorld();
	if (!World || !CharacterOwner)
	{
		return false;
	}

	const UCapsuleComponent* Capsule = CharacterOwner->GetCapsuleComponent();
	const float Radius = Capsule ? Capsule->GetScaledCapsuleRadius() : 34.f;

	FCollisionQueryParams Params(SCENE_QUERY_STAT(WebSlingerCrawlProbe), false, CharacterOwner);
	return World->SweepSingleByChannel(
		Out,
		From,
		From + Dir * (Radius + CrawlProbeDistance),
		FQuat::Identity,
		ECC_Visibility,
		FCollisionShape::MakeSphere(Radius * 0.5f),
		Params);
}

void UWebSlingerMovementComponent::PhysWallCrawl(float DeltaTime, int32 Iterations)
{
	if (DeltaTime < MIN_TICK_TIME)
	{
		return;
	}
	if (!CharacterOwner || !UpdatedComponent)
	{
		FallOut(DeltaTime, Iterations);
		return;
	}

	RestorePreAdditiveRootMotionVelocity();

	// Re-acquire the surface every frame. Crawling off an edge should drop you.
	FHitResult Surface;
	if (!TraceCrawlSurface(UpdatedComponent->GetComponentLocation(), -CrawlSurfaceNormal, Surface))
	{
		FallOut(DeltaTime, Iterations);
		return;
	}
	CrawlSurfaceNormal = Surface.ImpactNormal;

	// Input is camera-relative, so flatten it onto the surface. Looking at the
	// wall you are on would otherwise cancel all movement.
	const FVector InputDir = FVector::VectorPlaneProject(Acceleration.GetSafeNormal(), CrawlSurfaceNormal).GetSafeNormal();
	const FVector Target = InputDir * MaxCrawlSpeed;
	Velocity = FMath::VInterpTo(Velocity, Target, DeltaTime, CrawlAcceleration);

	// Hold a constant gap, so the capsule tracks bumps instead of catching them.
	const UCapsuleComponent* Capsule = CharacterOwner->GetCapsuleComponent();
	const float Radius = Capsule ? Capsule->GetScaledCapsuleRadius() : 34.f;
	const float Gap = Surface.Distance - Radius - CrawlStickDistance;
	const FVector Stick = -CrawlSurfaceNormal * FMath::Clamp(Gap, -CrawlProbeDistance, CrawlProbeDistance);

	Iterations++;
	bJustTeleported = false;
	const FVector Delta = Velocity * DeltaTime + Stick;
	const FQuat Rot = UpdatedComponent->GetComponentQuat();

	FHitResult Hit(1.f);
	SafeMoveUpdatedComponent(Delta, Rot, true, Hit);

	if (Hit.IsValidBlockingHit())
	{
		// Running into an inside corner: adopt the new face and keep going.
		SlideAlongSurface(Delta, 1.f - Hit.Time, Hit.Normal, Hit, true);
		if (Hit.ImpactNormal.Z <= MaxCrawlableFloorZ)
		{
			CrawlSurfaceNormal = Hit.ImpactNormal;
		}
	}
}
